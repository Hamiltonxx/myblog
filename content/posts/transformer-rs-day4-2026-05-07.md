+++
title = "用 Rust 手写 Transformer —— Day 4：Attention 到底在算什么？"
description = "把 Q、K、V 的矩阵乘法拆开来看，才明白 attention 不是在「关注」什么，而是在做一次可微分的加权检索。"
date = 2026-05-07

[taxonomies]
categories = ["学习"]
tags = ["rust", "transformer", "ndarray", "deep-learning", "attention"]

[extra]
lang = "zh"
toc = true
math = true
+++

今天把单头 Attention 的前向跑通了，2 个测试全过。但更有意思的是——写完这 6 行代码之后，我终于搞清楚 Q、K、V 这三个矩阵到底在干什么。

---

## Attention 是一次可微分的检索

先说结论：Attention 本质上是**软检索（soft retrieval）**。

想象一个键值数据库。你用一个 Query 去查，数据库里有一堆 Key-Value 对。传统数据库是硬匹配——Key 对上了就返回 Value，对不上就没有。

Attention 的改造是：把"对不对得上"变成一个连续的相似度分数，再对所有 Value 做加权平均。每个位置都能看到其他所有位置，只是"看多少"由分数决定。

论文里的完整公式：

$$\text{Attention}(Q, K, V) = \text{softmax}\!\left(\frac{QK^\top}{\sqrt{d_k}}\right)V$$

```rust
let scores = matmul(&q, &k.t().to_owned()) / scale; // Q · K^T：算相似度
let attn = softmax(&scores);                         // 归一化成概率
let context = matmul(&attn, &v);                     // 加权求和 Value
```

三行代码，三个步骤，就是全部。

---

## Q、K、V 从哪来

Q、K、V 都是从同一个输入 `x` 线性投影出来的：

```rust
let q = matmul(x, &self.w_q); // (seq, d_model) · (d_model, d_k) = (seq, d_k)
let k = matmul(x, &self.w_k);
let v = matmul(x, &self.w_v);
```

同一个 `x`，乘三个不同的权重矩阵，得到三个不同的表示。

这里有个微妙的地方：**Q 和 K 是用来"比较"的，V 是用来"输出"的**，所以它们承担的角色不同，自然用不同的投影。训练过程中，模型会自己学出来：W_q 和 W_k 应该把输入映射到适合做相似度匹配的空间，W_v 映射到适合作为输出内容的空间。

---

## scores 矩阵长什么样

$QK^\top$ 的结果是一个 $(T \times T)$ 的矩阵，第 $[i, j]$ 个元素是位置 $i$ 的 Query 和位置 $j$ 的 Key 的内积：

$$\text{scores}[i][j] = Q_i \cdot K_j = \sum_{k=1}^{d_k} Q_{ik} \cdot K_{jk}$$

这个值越大，说明位置 $i$ 和位置 $j$ 的内容越"相关"。之后 softmax 把每一行归一化成概率分布——每个位置的注意力权重加起来等于 1：

$$\text{attn}[i][j] = \frac{\exp(\text{scores}[i][j])}{\sum_{j'} \exp(\text{scores}[i][j'])}$$

这也是为什么测试里要验证行和：

```rust
for row in weights.axis_iter(Axis(0)) {
    let s: f32 = row.sum();
    assert!((s - 1.0).abs() < 1e-5);
}
```

不是在验证数值对不对，是在验证 softmax 的语义对不对——每个位置把 100% 的注意力分配出去，不多不少。

---

## 为什么除以 sqrt(d_k)

假设 $Q_i$ 和 $K_j$ 的每个分量都是独立的标准正态分布（均值 0、方差 1），那么它们的点积：

$$Q_i \cdot K_j = \sum_{k=1}^{d_k} Q_{ik} K_{jk}$$

是 $d_k$ 个独立随机变量之和，方差为 $d_k$，标准差为 $\sqrt{d_k}$。

`d_k` 一大，`scores` 的绝对值就会很大，进 softmax 之后概率几乎全压在最大值那一项。softmax 的梯度是 $s_i(1 - s_i)$，趋近于 1 的地方梯度接近 0，其他位置梯度也接近 0——整层失去学习能力。

除以 $\sqrt{d_k}$ 把标准差归一化回 1，scores 落在 softmax 梯度充足的区域：

```rust
let scale = (self.d_k as f32).sqrt();
let scores = matmul(&q, &k.t().to_owned()) / scale;
```

这一行如果漏掉，训练早期梯度就会消失，loss 不会动。

---

## forward 返回两个值

```rust
pub fn forward(&self, x: &Array2<f32>) -> (Array2<f32>, Array2<f32>) {
    // ...
    (out, attn)
}
```

返回 `attn`（注意力权重矩阵）不是为了可视化，是因为反向传播需要它。

`context = attn · V` 这一步，反向传播时要算 $\frac{\partial L}{\partial \text{attn}} = \frac{\partial L}{\partial \text{context}} \cdot V^\top$。如果 `attn` 在前向里不存起来，反向就得重新算一遍 softmax，多花一倍时间。这是手写反向传播的惯例：前向里凡是反向会用到的中间值，都顺手存下来。

---

## 测试结果

```
running 2 tests
test layers::attention::tests::test_output_shape ... ok
test layers::attention::tests::test_attn_weights_sum_to_one ... ok

test result: ok. 2 passed; 0 failed
```

Day 5 做梯度验证，用数值微分检查反向传播是否正确——这才是真正考验理解的地方。
