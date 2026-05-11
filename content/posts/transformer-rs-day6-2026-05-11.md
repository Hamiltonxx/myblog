+++
title = "用 Rust 手写 Transformer —— Day 6：多头注意力和因果掩码"
description = "单头 Attention 只能学一种关系，多头让模型同时看多个角度；Causal Mask 让语言模型只能看过去——这两个设计背后的数学和动机，今天全部弄清楚。"
date = 2026-05-10

[taxonomies]
categories = ["学习"]
tags = ["rust", "transformer", "ndarray", "deep-learning", "attention", "causal-mask"]

[extra]
lang = "zh"
toc = true
math = true
+++

实现 Multi-Head Attention 和 Causal Mask，这两个机制是 Transformer 用于语言建模的两个关键设计。 背后的动机也值得认真想清楚。

---

## 为什么需要多头？

先回想单头 Attention 在做什么：给定序列里的每个位置，用 $Q \cdot K^\top$ 算出"谁和谁相关"，再用这个相关权重去加权平均 $V$。

问题是：**一个序列里，"相关性"可能同时存在很多种**。

举个例子，"The animal didn't cross the street because **it** was too tired."这句话里，"it" 这个词：

- 从**句法**角度，"it" 是主语，需要找到它所指代的名词（animal）
- 从**语义**角度，"tired" 修饰的对象是"it"，要把这个语义关联建立起来
- 从**位置**角度，"it" 在句子靠后，需要感知自己的相对位置信息

如果只有一个 head，一个 $Q \cdot K^\top$ 矩阵要同时捕获这三种关系——它做不到，或者说它只能捕获训练中"最强的那一种信号"，其他的被忽略了。

多头的解决方案很直接：**跑 $h$ 个独立的 Attention，每个 head 有自己的 $W_Q^{(i)}, W_K^{(i)}, W_V^{(i)}$，学不同的关系模式，最后把所有 head 的输出拼起来**。

---

## 多头的数学

原论文的定义：

$$\text{MultiHead}(Q, K, V) = \text{Concat}(\text{head}_1, \dots, \text{head}_h) \cdot W^O$$

其中每个 head：

$$\text{head}_i = \text{Attention}(Q W_Q^{(i)},\ K W_K^{(i)},\ V W_V^{(i)})$$

参数量怎么控制？原来单头用 $d_k = d_{model}$，现在 $n$ 个 head 每个用 $d_k = d_{model} / n$，总参数量不变，但"看问题的角度"变成了 $n$ 个。

原论文里 $d_{model} = 512$，$n_{heads} = 8$，所以每个 head 的 $d_k = 64$。

---

## 实现：一次投影，按 head 切片

最直接的实现是给每个 head 存独立的权重矩阵，但更高效的做法是**把所有 head 的权重合并成一个大矩阵，一次 `matmul` 完成所有投影，再按 head 切片**：

```rust
pub struct MultiHeadAttention {
    pub w_q: Array2<f32>,  // (d_model, n_heads * d_k)  ← 所有 head 的 W_Q 拼在一起
    pub w_k: Array2<f32>,
    pub w_v: Array2<f32>,
    pub w_o: Array2<f32>,  // (n_heads * d_k, d_model)
    pub n_heads: usize,
    pub d_k: usize,
}
```

前向传播：

```rust
// 一次矩阵乘法，得到所有 head 的 Q/K/V
let q_full = matmul(x, &self.w_q); // (seq, n_heads * d_k)
let k_full = matmul(x, &self.w_k);
let v_full = matmul(x, &self.w_v);

// 按 head 切片，独立跑 attention
for h in 0..self.n_heads {
    let start = h * self.d_k;
    let end   = start + self.d_k;
    let q_h = q_full.slice(s![.., start..end]).to_owned(); // (seq, d_k)
    let k_h = k_full.slice(s![.., start..end]).to_owned();
    let v_h = v_full.slice(s![.., start..end]).to_owned();
    // ... attention ...
}
```

最后把所有 head 的输出沿 axis=1 拼接，再经过 $W^O$ 投影回 `d_model`：

```rust
let views: Vec<_> = head_contexts.iter().map(|a| a.view()).collect();
let concat = concatenate(Axis(1), &views).unwrap(); // (seq, n_heads * d_k)
let out = matmul(&concat, &self.w_o);               // (seq, d_model)
```

完整的 shape 流：

```
x:          (seq, d_model)
  ↓ × W_q/W_k/W_v
q/k/v_full: (seq, n_heads * d_k)
  ↓ 按 head 切列
q_h/k_h/v_h: (seq, d_k)     × n_heads 份
  ↓ scores + mask → softmax → × v_h
context_h:  (seq, d_k)       × n_heads 份
  ↓ concatenate(Axis(1))
concat:     (seq, n_heads * d_k)  == (seq, d_model)
  ↓ × W_o
out:        (seq, d_model)
```

---

## Causal Mask：为什么语言模型不能偷看未来

普通的 Transformer（比如用于翻译的 encoder）里，每个位置可以自由地关注序列里所有其他位置——这是合理的，因为翻译时整句话都已知。

但**语言模型的任务是预测下一个词**：给定 `["The", "cat", "sat"]`，预测 `"on"`。这时位置 3（"on"）在训练中是已知的，但推理时它是我们要预测的目标。如果模型在训练时被允许看到位置 3 来预测位置 3，它直接抄答案就好了，什么也学不到。

因果掩码（Causal Mask）的作用：**训练时强制位置 $t$ 只能看到位置 $0, 1, \dots, t$，不能看 $t+1$ 之后的任何位置**。推理时自然满足这个约束（未来的 token 还没生成），训练时需要人工施加。

---

## Causal Mask 的数学

做法是在 softmax **之前**，把 scores 矩阵的上三角加上 $-\infty$：

$$\tilde{s}_{ij} = s_{ij} + m_{ij}$$

其中 $m_{ij} = 0$（$j \leq i$），$m_{ij} = -\infty$（$j > i$）。

然后 softmax：

$$\text{attn}_{ij} = \frac{e^{\tilde{s}_{ij}}}{\sum_{j'} e^{\tilde{s}_{ij'}}}$$

对于 $j > i$ 的位置，$e^{-\infty} = 0$，所以它们的注意力权重恰好为 0，不参与加权平均。

对于合法位置 $j \leq i$，加了 0，不影响结果。

以 4 个 token 为例，mask 矩阵长这样（0 表示可看，$-\infty$ 表示屏蔽）：

```
     t=0   t=1   t=2   t=3
i=0 [  0,   -∞,   -∞,   -∞ ]   token 0 只能看自己
i=1 [  0,    0,   -∞,   -∞ ]   token 1 能看 0 和 1
i=2 [  0,    0,    0,   -∞ ]   token 2 能看 0、1、2
i=3 [  0,    0,    0,    0 ]   token 3 能看所有
```

这在 Rust 里一行生成：

```rust
pub fn causal_mask(seq: usize) -> Array2<f32> {
    Array2::from_shape_fn((seq, seq), |(i, j)| {
        if j > i { f32::NEG_INFINITY } else { 0.0 }
    })
}
```

---

## 一个容易踩的细节

softmax 里做了数值稳定处理（减最大值）。有了 $-\infty$ 之后，每行的最大值可能就是某个合法位置的 score，$-\infty$ 减去任何有限数还是 $-\infty$，$e^{-\infty}$ 还是 0，不影响结果。所以 mask 和数值稳定 softmax 是兼容的，不需要特殊处理。

---

## 测试

四个测试验证了不同方面：

```rust
// mask 矩阵的值对不对
test_causal_mask_values

// 加了 mask 之后，attn[i][j] 当 j > i 时是否真的为 0
test_causal_mask_blocks_future

// 每行的 attention 权重加起来是否等于 1
test_attn_weights_sum_to_one

// 输出 shape 是否正确，head 数量和 shape 是否对
test_output_shape
```

```
running 13 tests
...
test layers::multihead_attention::tests::test_causal_mask_values ... ok
test layers::multihead_attention::tests::test_causal_mask_blocks_future ... ok
test layers::multihead_attention::tests::test_output_shape ... ok
test layers::multihead_attention::tests::test_attn_weights_sum_to_one ... ok
...

test result: ok. 13 passed; 0 failed
```

---

明天 Day 7：FFN + LayerNorm + 残差连接，把一个完整的 Transformer Block 拼出来。LayerNorm 的反向传播是后面最绕的部分，前向先把结构搭好。
