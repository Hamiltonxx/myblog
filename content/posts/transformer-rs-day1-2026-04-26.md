+++
title = "用 Rust 手写 Transformer —— Day 1：矩阵运算和梯度验证"
description = "从零用 Rust 实现 matmul、softmax 的前向和反向传播，并用数值梯度验证正确性——这才是真正理解深度学习的方式。"
date = 2026-04-25

[taxonomies]
categories = ["学习"]
tags = ["rust", "transformer", "ndarray", "deep-learning", "反向传播"]

[extra]
lang = "zh"
toc = true
+++

今天是"两周手写 Transformer"计划的第一天。目标很简单：把矩阵运算实现出来，写反向传播，然后用数值验证证明梯度是对的。

没有 PyTorch，没有 autograd。

---

## 为什么要手写梯度

用 PyTorch 调 `loss.backward()` 一行搞定，但你真的知道 softmax 的梯度长什么样吗？

手写一遍之后，这些都不再是魔法。这个计划的核心节奏就是：**实现 → 推导梯度 → 数值验证**，每个操作都要过这三关。

---

## 热身：ndarray 基础

先写了一个 `examples/ndarr.rs` 把 ndarray 的常用操作摸了一遍。

```rust
use ndarray::{array, Array1, Array2, Axis, s};

fn main() {
    // 一维数组
    let a: Array1<f64> = Array1::zeros(5);
    let b = array![1.0, 2.0, 3.0];
    println!("{:?}  {:?}", a, b);

    // 二维数组
    let m: Array2<f64> = Array2::zeros((3, 4));
    let m2 = array![[1.0, 2.0], [3.0, 4.0]];
    println!("{:?}\n{:?}", m, m2);

    // 等差序列
    let r = Array1::linspace(0.0, 1.0, 11);   // 0.0 到 1.0，11 个点
    let r2 = Array1::range(0.0, 10.0, 1.0);   // 步长为 1.0
    println!("{:?}\n{:?}", r, r2);

    // reshape：把一维变成 (2, 5) 的矩阵
    let m2 = r2.clone().into_shape((2, 5)).unwrap();
    println!("{:?}", m2);

    // 转置：.t() 返回的是 view，不拷贝数据
    let t = m2.t();
    println!("{:?}", t);

    // 维度信息
    println!("{:?}  {}  {}", m2.shape(), m2.ndim(), m2.len());

    // 索引与切片（s! 宏是 ndarray 的切片语法）
    let v = m2[[1, 2]];
    let row = m2.slice(s![0, ..]);      // 第 0 行
    let col = m2.slice(s![.., 1]);      // 第 1 列
    let sub = m2.slice(s![.., 1..3]);   // 子矩阵
    let step = m2.slice(s![.., ..; 2]); // 步长切片（每隔一列）
    println!("{:?}\n{:?}\n{:?}\n{:?}", row, col, sub, step);

    println!("数学运算");
    let a = array![1.0, 2.0, 3.0];
    let b = array![4.0, 5.0, 6.0];
    let c = &a + &b;           // 逐元素加（注意要用引用）
    let d = &a * 2.0;          // 标量乘
    let e = a.mapv(f64::exp);  // 逐元素 exp
    println!("{:?}\n{:?}\n{:?}", c, d, e);

    // 矩阵乘法：.dot() 同时支持矩阵乘矩阵和向量点积
    let x = array![[1.0, 2.0], [3.0, 4.0]];
    let y = array![[5.0, 6.0], [7.0, 8.0]];
    let z = x.dot(&y);        // 矩阵乘矩阵，结果 2x2
    let dot_val = a.dot(&b);  // 向量点积，结果是标量
    println!("{:?}\n{}", z, dot_val);

    // 归约：把整个数组折叠成一个值
    let sum = a.sum();
    let mean = a.mean().unwrap();
    let max = a.fold(f64::NEG_INFINITY, |acc, &x| acc.max(x));

    // 按轴归约：沿某个维度折叠，另一个维度保留
    // Axis(0) = 消灭"行"这个维度 → 每列求和，shape (5,)
    // Axis(1) = 消灭"列"这个维度 → 每行求和，shape (2,)
    let col_sum = m2.sum_axis(Axis(0));
    let row_sum = m2.sum_axis(Axis(1));
    println!("{:?}\n{:?}", col_sum, row_sum);
}
```

**几个值得注意的地方：**

**切片用 `s!` 宏**，语法和 Python 的 `[0, :]` 很像，但需要显式引入这个宏。`s![.., 1..3]` 等价于 Python 的 `[:, 1:3]`。

**逐元素运算要用引用**，写 `&a + &b` 而不是 `a + b`，否则会发生 move，之后就用不了 `a` 了。这是 Rust 所有权规则的直接体现。

**`.mapv()` 是逐元素变换的标准方式**，接受一个函数，返回新数组。`.map()` 也能用，但返回的是引用，多数情况下 `mapv` 更方便。

**按轴归约的记忆方法**：`Axis(n)` 里的 `n` 就是**消失的那个维度的下标**。原 shape `(2, 5)`，`Axis(1)` 之后变成 `(2,)`，第 1 维消失了，留下的是每行的汇总值。

---

## 核心：tensor.rs

热身完就进入正题，实现 `src/tensor.rs`。

```rust
use ndarray::{Array1, Array2, Axis};

pub fn matmul(a: &Array2<f32>, b: &Array2<f32>) -> Array2<f32> {
    a.dot(b)
}

// dL/dA = grad_out · B^T
// dL/dB = A^T · grad_out
pub fn matmul_backward(
    a: &Array2<f32>,
    b: &Array2<f32>,
    grad_out: &Array2<f32>,
) -> (Array2<f32>, Array2<f32>) {
    let grad_a = grad_out.dot(&b.t());
    let grad_b = a.t().dot(grad_out);
    (grad_a, grad_b)
}

pub fn softmax(x: &Array2<f32>) -> Array2<f32> {
    let max = x.map_axis(Axis(1), |r| r.fold(f32::NEG_INFINITY, |a, &b| a.max(b)));
    let exp = (x - &max.insert_axis(Axis(1))).mapv(f32::exp);
    &exp / &exp.sum_axis(Axis(1)).insert_axis(Axis(1))
}

// softmax 梯度: grad_in[i] = s[i] * (grad_out[i] - sum(grad_out * s))
pub fn softmax_backward(s: &Array2<f32>, grad_out: &Array2<f32>) -> Array2<f32> {
    let dot = (s * grad_out).sum_axis(Axis(1));
    let dot = dot.insert_axis(Axis(1));
    s * (grad_out - &dot)
}

pub fn broadcast_add(x: &Array2<f32>, bias: &Array1<f32>) -> Array2<f32> {
    x + bias
}

// grad_x = grad_out（形状不变）
// grad_bias = grad_out 沿 axis=0 求和
pub fn broadcast_add_backward(grad_out: &Array2<f32>) -> (Array2<f32>, Array1<f32>) {
    let grad_bias = grad_out.sum_axis(Axis(0));
    (grad_out.to_owned(), grad_bias)
}

// transpose 直接用 .t()，反向传播时再 .t() 一次即可
```

逐个说明：

### matmul_backward：链式法则的矩阵形式

`C = A · B`，loss 对 A 的梯度是 `dL/dA = grad_out · B^T`，对 B 是 `dL/dB = A^T · grad_out`。

这是链式法则在矩阵上的展开形式。直觉上：**梯度沿着转置方向流回去**。不理解也没关系，验证过了就是对的，反复推导几次自然就记住了。

### softmax：减 max 是关键

softmax 公式是 `exp(x) / sum(exp(x))`，但直接算会溢出（`exp(1000)` 是 inf）。标准做法是先减掉每行的最大值：

```
softmax(x) = softmax(x - max(x))  ← 数学上等价，数值上稳定
```

代码里的 `insert_axis(Axis(1))` 是为了广播：`max` 是 shape `(n,)` 的一维数组，要减掉一个 `(n, d)` 的矩阵，需要先变成 `(n, 1)` 才能自动广播。

### softmax_backward：雅可比矩阵化简后的结果

softmax 的梯度推导是本项目最有价值的练习之一。完整推导需要用到雅可比矩阵，化简后得到：

```
grad_in[i] = s[i] * (grad_out[i] - Σ(s * grad_out))
```

代码里 `sum_axis(Axis(1))` 是对每行求那个 `Σ`，`insert_axis` 再把它广播回 `(n, d)` 的形状做减法。

### broadcast_add_backward：偏置梯度为什么要求和

把矩阵加偏置向量（每行加同一个向量），反向时偏置的梯度是 `grad_out` 沿 axis=0 求和。原因是偏置被"广播"到了每一行，每行都对它有贡献，所以要把所有行的梯度加起来。

---

## 梯度验证：finite difference

每写一个梯度，立刻用数值方法验证。思路是：微微扰动输入，看 loss 变化量是否和解析梯度一致。

```rust
fn numerical_grad<F: Fn(&Array2<f32>) -> f32>(
    f: F,
    x: &Array2<f32>,
    eps: f32,
) -> Array2<f32> {
    let mut grad = Array2::zeros(x.dim());
    for i in 0..x.nrows() {
        for j in 0..x.ncols() {
            let mut xp = x.clone();
            let mut xm = x.clone();
            xp[[i, j]] += eps;
            xm[[i, j]] -= eps;  // 注意是减，不是加
            grad[[i, j]] = (f(&xp) - f(&xm)) / (2.0 * eps);
        }
    }
    grad
}
```

用 `f32` 时 `eps` 要用 `1e-3`，不能用 `1e-4`——后者因为 f32 精度不够，分子 `f(xp) - f(xm)` 会损失有效位，导致数值梯度不准。这个坑踩了才知道。

最终两个测试都通过：

```
running 2 tests
test tensor::tests::test_matmul_grad ... ok
test tensor::tests::test_softmax_grad ... ok

test result: ok. 2 passed
```

---

## 下一步

Day 2 继续完善 tensor 层，然后进入 Embedding 和位置编码。前向传播跑通之前，每新增一个操作都要过数值验证这关。
