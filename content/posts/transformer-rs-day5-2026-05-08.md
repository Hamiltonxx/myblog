+++
title = "用 Rust 手写 Transformer —— Day 5：给单头注意力增加缓存"
description = "不跑随机权重，换成全是单位矩阵，把 Attention 每一步手算一遍——数字对上了，才算真的读懂了。"
date = 2026-05-08

[taxonomies]
categories = ["学习"]
tags = ["rust", "transformer", "ndarray", "deep-learning", "attention"]

[extra]
lang = "zh"
toc = true
math = true
+++

今天没写多少新代码，主要在读昨天的代码，顺手把 `forward` 改造了一下，加了缓存结构，然后用一个手算例子把结果验证了一遍。

---

## 先把代码读懂，再往前走

昨天 `SingleHeadAttention` 的前向跑通了，测试也过了。但我没急着继续——测试过了不代表真懂了，只是证明 shape 对、行和为 1，不代表每一步的数字是对的。

所以今天先花时间把 Day 4 的代码读透，弄清楚三个问题：

1. `d_model` 和 `d_k` 分别是什么
2. `rand::random::<f32>() * 2.0 * scale - scale` 这个初始化在干什么
3. `k.t().to_owned()` 为什么要加 `to_owned()`

---

## d_model 和 d_k

`d_model` 是每个 token 的向量维度。输入 `x` 的 shape 是 `(seq, d_model)`，每一行是一个 token，有 `d_model` 个数。

`d_k` 是 Q/K/V 投影后的维度，比 `d_model` 小或相等。投影矩阵的作用是把每个 token 从 `d_model` 维变换到 `d_k` 维，然后在这个更小的空间里做点积：

```
x: (seq, d_model)
   × W_q: (d_model, d_k)
   = Q: (seq, d_k)
```

多头 Attention 里，`d_k = d_model / n_heads`。单头就直接取 `d_k = d_model`。

---

## 初始化的 scale 和前向的 scale 是两回事

`new()` 里：

```rust
let scale = (d_k as f32).sqrt().recip(); // 1/√d_k，用于初始化权重范围
let rand_mat = |rows, cols| {
    Array2::from_shape_fn((rows, cols), |_| rand::random::<f32>() * 2.0 * scale - scale)
};
```

这是 Xavier 初始化的简化版，目的是让初始权重落在 $[-1/\sqrt{d_k},\ 1/\sqrt{d_k}]$ 范围内，防止训练开始时激活值太大或太小。

`forward()` 里：

```rust
let scale = (self.d_k as f32).sqrt(); // √d_k，用于缩放 scores
let scores = matmul(&q, &k.t().to_owned()) / scale;
```

这是防止 softmax 饱和的缩放，把点积的方差归一化回 1，原理昨天写过了。

**两个地方都用了 `√d_k`，但目的完全不同，不要混。**

---

## 用手算例子验证

光跑随机权重测不出什么。真正的验证方式是：**给定一组特殊的权重和输入，把结果手算出来，再和代码输出对比**。

取最简单的情况：

```
seq = 2, d_model = 2, d_k = 2
W_q = W_k = W_v = W_o = I（单位矩阵）
x = I（单位矩阵）
```

**Step 1：线性投影**

$$Q = K = V = x \cdot I = x = \begin{bmatrix}1&0\\0&1\end{bmatrix}$$

**Step 2：scores**

$$QK^\top = x \cdot x^\top = I \cdot I = I$$

$$\text{scores} = \frac{I}{\sqrt{2}} = \begin{bmatrix}0.707&0\\0&0.707\end{bmatrix}$$

**Step 3：softmax（按行）**

第 0 行 $[0.707,\ 0]$：

$$\text{attn}[0,0] = \frac{e^{0.707}}{e^{0.707}+e^0} = \frac{2.028}{3.028} \approx 0.6699$$

$$\text{attn}[0,1] = \frac{1}{3.028} \approx 0.3301$$

**Step 4：context = attn · V = attn · I = attn**

**Step 5：out = context · W_o = attn · I = attn**

所以最终 `out ≈ [[0.6699, 0.3301], [0.3301, 0.6699]]`。

物理意义直观：token 0 的输出 = 67% 自己的 Value + 33% token 1 的 Value。这就是 Attention 在做的事——加权混合。

---

## 把手算结果写成测试

```rust
#[test]
fn test_identity_weights_manual() {
    let d = 2;
    let eye = Array2::<f32>::eye(d);
    let layer = SingleHeadAttention {
        w_q: eye.clone(), w_k: eye.clone(),
        w_v: eye.clone(), w_o: eye.clone(),
        d_k: d,
    };
    let x = Array2::<f32>::eye(d);
    let (out, cache) = layer.forward(&x);

    // 手算：attn[0,0] ≈ 0.6699，attn[0,1] ≈ 0.3301
    assert!((cache.attn[[0, 0]] - 0.6699).abs() < 1e-3);
    assert!((cache.attn[[0, 1]] - 0.3301).abs() < 1e-3);

    // W_v = W_o = I，所以 out == attn
    for i in 0..d {
        for j in 0..d {
            assert!((out[[i, j]] - cache.attn[[i, j]]).abs() < 1e-5);
        }
    }
}
```

跑过了。数字对上，说明代码和推导是一致的。

---

## 顺手把 forward 改造成带缓存的版本

原来的 `forward` 返回 `(out, attn)`，改名成 `forward_v1` 保留。

新的 `forward` 返回 `(out, AttentionCache)`，把所有中间值存下来：

```rust
pub struct AttentionCache {
    pub x:       Array2<f32>,  // (seq, d_model)
    pub q:       Array2<f32>,  // (seq, d_k)
    pub k:       Array2<f32>,  // (seq, d_k)
    pub v:       Array2<f32>,  // (seq, d_k)
    pub scores:  Array2<f32>,  // (seq, seq) softmax 前
    pub attn:    Array2<f32>,  // (seq, seq) softmax 后
    pub context: Array2<f32>,  // (seq, d_k)
}
```

Day 9-10 写反向传播时，这些值全都会用到。现在存好，到时候不用再算一遍。

---

## 测试结果

```
running 9 tests
test layers::attention::tests::test_identity_weights_manual ... ok
test layers::attention::tests::test_output_shape ... ok
test layers::attention::tests::test_attn_weights_sum_to_one ... ok
...

test result: ok. 9 passed; 0 failed
```

---

明天 Day 6：多头 + Causal Mask。把 `d_model` 按 `n_heads` 拆开，并行跑 `n_heads` 个单头，加上上三角 mask 让 token 看不到未来。
