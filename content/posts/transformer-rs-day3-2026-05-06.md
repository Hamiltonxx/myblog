+++
title = "用 Rust 手写 Transformer —— Day 3：Token 怎么变成向量？"
description = "Embedding 就是一张大表，位置编码不过是 sin/cos——但把这两行公式真正写进代码，才会发现细节全在魔鬼里。"
date = 2026-05-06

[taxonomies]
categories = ["学习"]
tags = ["rust", "transformer", "ndarray", "deep-learning", "embedding", "positional-encoding"]

[extra]
lang = "zh"
toc = true
+++

实现 Embedding 查表和正弦位置编码，新建了 `src/layers/` 模块，4 个测试全部通过。

---

## Token 是什么

Token 就是文本被切割后的最小单位，把一段文字切成一块一块，每一块是一个 token。

字符级（这个项目用的）：

```
"Hello" → ['H', 'e', 'l', 'l', 'o']  →  5 个 token
```

每个字符是一个 token，`vocab_size = 65`（莎士比亚语料里出现的所有字符数）。

词级（更常见）：

```
"I love cats" → ["I", "love", "cats"]  →  3 个 token
```

神经网络只认数字，所以每个 token 要先映射成一个整数 id，再由 Embedding 层查表变成向量：

```
'H' → 40  →  查第 40 行  →  [0.1, 0.3, ..., 0.9]   (d_model 个数)
'e' → 28  →  查第 28 行  →  [...]
'l' → 37  →  查第 37 行  →  [...]
```

这才是进入 Transformer 的输入 `x: (seq, d_model)`。

---

## 今天做了什么

```
src/
  layers/
    mod.rs
    embedding.rs   ← 今天新增
  tensor.rs
  main.rs
```

两件事：
1. `Embedding`：给定 token id 列表，查出对应的向量（本质就是按行索引一张大矩阵）
2. `positional_encoding`：用正弦/余弦公式生成位置信息，让模型知道"第几个词"

---

## Embedding：最朴素的查表

语言模型处理的输入是 token id，比如 `[3, 1, 4, 1, 5]`。但神经网络只吃浮点数，所以需要把每个 id 映射成一个向量。

做法很直白：维护一张形状为 `(vocab_size, d_model)` 的矩阵，给定 id，就取出对应的那一行。

```rust
pub struct Embedding {
    pub weight: Array2<f32>, // (vocab_size, d_model)
}

impl Embedding {
    pub fn new(vocab_size: usize, d_model: usize) -> Self {
        let scale = (d_model as f32).sqrt().recip();
        let weight = Array2::from_shape_fn((vocab_size, d_model), |_| {
            rand::random::<f32>() * 2.0 * scale - scale
        });
        Self { weight }
    }

    pub fn forward(&self, ids: &[usize]) -> Array2<f32> {
        let d = self.weight.ncols();
        Array2::from_shape_fn((ids.len(), d), |(t, j)| self.weight[[ids[t], j]])
    }
}
```

初始化用 `[-scale, scale)` 均匀分布，`scale = 1 / sqrt(d_model)`。这个范围不是随便选的：如果初始权重太大，softmax 一上来就饱和，梯度直接消失。

`forward` 那一行 `Array2::from_shape_fn((ids.len(), d), |(t, j)| ...)` 是在用一个闭包逐元素填充新矩阵——给定 `(行, 列)` 坐标，查对应 token 的权重。比 `map` + `stack` 的写法干净一些。

---

## Embedding 反向：scatter add

前向是"按 id 取行"，反向就是"按 id 把梯度加回去"。

如果同一个 token 在序列里出现了多次，它对应的那一行会收到多份梯度，需要全部累加：

```rust
pub fn backward(&self, ids: &[usize], grad_out: &Array2<f32>) -> Array2<f32> {
    let mut grad_w = Array2::zeros(self.weight.dim());
    for (t, &id) in ids.iter().enumerate() {
        grad_w.row_mut(id).scaled_add(1.0, &grad_out.row(t));
    }
    grad_w
}
```

`scaled_add(1.0, &v)` 等价于 `row += v`，但避免了额外分配。

测试用例是 `ids = [0, 2, 2]`，id=2 出现两次，对应行的梯度应该是 2，id=1 没出现过，梯度是 0：

```rust
assert!((grad_w[[2, 0]] - 2.0).abs() < 1e-6);
assert!(grad_w[[1, 0]].abs() < 1e-6);
```

---

## 位置编码：用 sin/cos 告诉模型"第几个词"

Attention 机制本身是顺序无关的——`[A, B, C]` 和 `[C, B, A]` 丢进去结果一样。位置编码就是为了打破这个对称性。

Transformer 原论文用的公式：

```
PE[pos, 2i]   = sin(pos / 10000^(2i / d_model))
PE[pos, 2i+1] = cos(pos / 10000^(2i / d_model))
```

直觉是：不同频率的 sin/cos 组合出来，每个位置的编码都是唯一的，而且相邻位置之间的差异是平滑的，不会突变。

代码实现一行搞定：

```rust
pub fn positional_encoding(seq_len: usize, d_model: usize) -> Array2<f32> {
    Array2::from_shape_fn((seq_len, d_model), |(pos, j)| {
        let i = j / 2;
        let denom = 10000_f32.powf(2.0 * i as f32 / d_model as f32);
        if j % 2 == 0 {
            (pos as f32 / denom).sin()
        } else {
            (pos as f32 / denom).cos()
        }
    })
}
```

`j / 2` 把列下标映射到 `i`，`j % 2` 判断偶数列用 sin、奇数列用 cos。

验证方式：`pos=0` 时，所有偶数列是 `sin(0) = 0`，所有奇数列是 `cos(0) = 1`：

```rust
for j in (0..8).step_by(2) {
    assert!(pe[[0, j]].abs() < 1e-6);
}
for j in (1..8).step_by(2) {
    assert!((pe[[0, j]] - 1.0).abs() < 1e-6);
}
```

---

## 测试结果

```
running 4 tests
test layers::embedding::tests::test_pe_shape ... ok
test layers::embedding::tests::test_pe_pos0 ... ok
test layers::embedding::tests::test_embedding_shape ... ok
test layers::embedding::tests::tet_embedding_backward ... ok

test result: ok. 4 passed; 0 failed
```

---

## 下一步

Day 4 进入单头 Attention 的前向传播：`Q K V` 线性投影 → `QK^T` → scale → softmax → `× V`。

这是整个 Transformer 最核心的部分，先跑通单头，多头只是并行跑多个单头而已。
