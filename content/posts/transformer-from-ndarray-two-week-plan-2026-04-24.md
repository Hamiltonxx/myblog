+++
title = "两周从零手写 Transformer：不用任何 ML 框架，只有 Rust"
description = "不调 PyTorch，不用 autograd，每一个梯度都自己推导——两周后，你才算真正懂 Transformer。"
date = 2026-04-23

[taxonomies]
categories = ["学习"]
tags = ["rust", "transformer", "deep-learning", "ndarray", "反向传播", "学习计划"]

[extra]
lang = "zh"
toc = true
+++

> 可能很多人和我一样，看过 Attention Is All You Need，跑过 Hugging Face, 但具体到最基本的 softmax 的梯度算？都不一定能理解透彻。
> 这个计划只有一个目标：用 Rust + ndarray，从零写出一个能训练的 Transformer，
> 每行代码都自己敲一遍，体会它的深意。

---

## 为什么要这么做

这个计划的灵感来自 Karpathy 的 `llm.c`——用最少的依赖，从头实现一个语言模型，逼自己真正理解每一层的工作原理。

区别在于：这次用 Rust，且**不借助任何 autograd**。

为什么？

**因为 autograd 是一张遮羞布。** 你调 `loss.backward()`，一行搞定所有梯度，感觉很厉害，但你不知道 LayerNorm 的梯度长什么样，不知道 softmax 求导为什么是 `S(1 - S)`，更不知道 attention 的反向传播为什么要那么写。

手写一遍之后，这些全都清楚了。PyTorch 帮你算的东西，你从此也能算。

对标项目：`llm.c`（C 语言版）。我们做的是 Rust 版，性能有保障，代码可读性更好。

最终验证场景：把莎士比亚全集扔进去训练，模型能生成风格相近的句子。这是 Karpathy 用过的经典 benchmark，效果直观，不需要 fancy 的评估指标。

---

## 项目结构

先看全貌，做事心里有数：

```
transformer-rs/
├── src/
│   ├── tensor.rs        # matmul, softmax 等基础操作
│   ├── layers/
│   │   ├── attention.rs
│   │   ├── ffn.rs
│   │   ├── norm.rs
│   │   └── embedding.rs
│   ├── model.rs         # 组装完整 Transformer
│   ├── train.rs         # loss, optimizer, 训练循环
│   └── main.rs
├── data/
│   └── tinyshakespeare.txt
└── tests/
    └── grad_check.rs    # 数值梯度验证
```

依赖极简：

```toml
[dependencies]
ndarray = { version = "0.16", features = ["rayon"] }
rand = "0.8"
serde_json = "1"  # 可选，保存权重用
```

就这三个。没有 ML 框架，没有 autograd，没有 CUDA binding。

---

## 里程碑计划（14 天）

每天抽出 4 ~ 6 小时，把基础打扎实。

---

## 第 1 周：前向传播

### Day 1-2 —— 地基：Tensor 操作层

**目标：把矩阵运算实现出来，并用数值验证正确性**

不是为了造轮子，是因为反向传播时要知道每个操作的梯度怎么算。ndarray 帮你做运算，但梯度逻辑得自己写。

```
实现：matmul / transpose / broadcast_add / softmax
验证：写 Python 对照脚本，和 numpy 结果逐元素比对
```

从 `matmul` 开始，立刻写反向，立刻验证——这是整个计划的核心节奏：

```rust
pub fn matmul(a: &Array2<f32>, b: &Array2<f32>) -> Array2<f32> {
    a.dot(b)
}

// 梯度：dL/dA = dL/dC · B^T，dL/dB = A^T · dL/dC
pub fn matmul_backward(
    a: &Array2<f32>,
    b: &Array2<f32>,
    grad_output: &Array2<f32>,
) -> (Array2<f32>, Array2<f32>) {
    let grad_a = grad_output.dot(&b.t());
    let grad_b = a.t().dot(grad_output);
    (grad_a, grad_b)
}
```

**Rust 能力：** ndarray Array2、方法链、借用规则初探

---

### Day 3 —— Embedding + Positional Encoding

**目标：把 token id 序列变成向量**

```
实现：token embedding 查表 / 正弦位置编码
验证：给定 [3, 1, 4, 1, 5]，输出 shape = (5, d_model) 的矩阵
```

正弦位置编码有个经典公式：

```
PE(pos, 2i)   = sin(pos / 10000^(2i/d_model))
PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))
```

实现不难，但要理解：模型靠这个知道每个 token 在序列里的位置，否则 attention 是顺序无关的。

**Rust 能力：** 二维数组索引、f32 数学函数

---

### Day 4-5 —— 单头 Attention 前向

**目标：把公式和代码完全对应起来，一行不差**

这是整个计划最核心的部分。先做单头，搞清楚之后多头只是并行跑多个单头。

```
实现：Q K V 线性投影 → QK^T → scale → softmax → × V
验证：手算一个 2×2 的例子，和代码输出对齐
```

scale 的作用是防止点积值太大导致 softmax 梯度消失：除以 `sqrt(d_k)`。

**Rust 能力：** 矩阵乘法链、shape 追踪

---

### Day 6 —— Multi-Head Attention + Causal Mask

**目标：单头变多头，加上因果掩码**

```
实现：split heads / 并行 attention / concat / 输出投影
实现：上三角 mask（让位置 t 看不到 t+1 之后的 token）
```

Causal mask 是语言模型区别于普通 Transformer 的关键——预测下一个词时，不能偷看未来。实现上就是在 softmax 之前，把上三角位置填成负无穷。

**Rust 能力：** 高维 ndarray（Array3/4）、map + zip 操作

---

### Day 7 —— FFN + LayerNorm + 残差

**目标：把一个完整的 Transformer Block 跑通**

```
实现：两层线性 + ReLU（FFN）
实现：LayerNorm（减均值、除方差、scale + shift）
实现：残差连接（直接相加）
验证：单个 Block 前向跑通，输入输出 shape 一致
```

LayerNorm 的实现看起来简单，但反向传播时梯度推导是这个项目里最绕的部分之一——Day 9 会专门对付它。

**Rust 能力：** 结构体组合、Vec<Layer> 层叠

---

### Day 8 —— 完整前向 + 文字采样

**目标：随机初始化权重，能生成（乱的）文字**

```
组装：N 个 Block 堆叠 / 输出 logits / temperature softmax 采样
验证：能输出文字就算过，这时候权重是随机的，内容肯定是乱码
```

这一天是第一个里程碑——**前向通了**。乱码不丢人，说明架构没问题。

---

## 第 2 周：反向传播 + 训练

### Day 9-10 —— 反向传播：最硬的部分

**目标：手动推导并实现每个操作的梯度**

这是整个计划最难的两天，也是最有价值的两天。

建议顺序：

```
matmul 梯度
→ softmax 梯度（Jacobian 矩阵，化简后很优雅）
→ attention 梯度（链式法则展开）
→ LayerNorm 梯度（最绕，建议先推导再实现）
```

**每个梯度都必须用数值验证（finite difference）：**

```rust
// 数值梯度检验：扰动输入，看 loss 变化量是否和解析梯度一致
fn finite_diff_check<F>(f: F, x: &Array2<f32>, eps: f32) -> Array2<f32>
where
    F: Fn(&Array2<f32>) -> f32,
{
    let mut grad = Array2::zeros(x.dim());
    for i in 0..x.nrows() {
        for j in 0..x.ncols() {
            let mut x_plus = x.clone();
            let mut x_minus = x.clone();
            x_plus[[i, j]] += eps;
            x_minus[[i, j]] -= eps;
            grad[[i, j]] = (f(&x_plus) - f(&x_minus)) / (2.0 * eps);
        }
    }
    grad
}
```

解析梯度和数值梯度的相对误差小于 `1e-4` 就算通过。**绝对不要攒到最后一起调——那时候根本不知道错在哪。**

**Rust 能力：** 闭包、泛型函数、多维数组迭代

---

### Day 11 —— SGD + 训练循环

**目标：loss 能下降，说明反向传播是对的**

```
实现：cross-entropy loss（logits → softmax → -log）
实现：SGD（参数 -= lr * 梯度）
跑通：loss 从 ~4.0 开始下降
```

先用 SGD，不用 Adam。原因是 SGD 足够简单，如果 loss 不降，100% 是反向传播有 bug，不会是优化器的问题。

**Rust 能力：** 可变借用、训练循环结构

---

### Day 12 —— Adam 优化器

**目标：加上 Adam，loss 下降明显变快**

```
实现：一阶矩 m / 二阶矩 v / bias correction
替换 SGD：lr 同样，看收敛速度的差异
```

Adam 在稀疏梯度（比如 embedding）上的效果比 SGD 好得多，这个项目里会体会非常明显。

**Rust 能力：** 状态持久化（把矩的状态存在 struct 里）

---

### Day 13 —— 训练莎士比亚

**目标：让模型真正学到东西**

```
数据：tinyshakespeare（~1MB，约 100 万字符）
下载：curl -O https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt
跑：loss 从 ~4.0 降到 ~1.5 说明模型在学
生成：看输出像不像莎士比亚的风格
```

1.5 附近的 loss 对应的生成内容大概是这样的：

```
KING RICHARD III:
So, but I have not been the lord,
And with the state of the world...
```

不完全通顺，但已经有莎士比亚的味道——单词选用、对话格式、人物称呼都开始像了。这就是语言模型"在学东西"的标志。

---

### Day 14 —— 整理 + 发布

**目标：代码整洁，文章写好，对外发布**

```
README 配架构图（用 ASCII 画也行）
每个模块写注释：解释为什么这么实现，不只是 what，要有 why
发布：blog.cirray.cn / V2EX / Reddit r/rust
```

---

## 风险预案

| 如果…… | 怎么办 |
|--------|--------|
| 梯度验证一直不过 | 逐层二分排查，先确认 matmul 再往上 |
| LayerNorm 反向搞不定 | 先用一个简化版（不带 scale/shift），后补 |
| 训练太慢 | 缩小模型（d_model=64, n_heads=2, n_layers=2），先跑通 |
| ndarray 维度对不上 | 打印每步的 shape，用 .dim() 检查 |
| 某天完全卡死 | 周末缓冲就是为这个准备的，不要跳天 |

---

## 每日节奏

```
09:00 - 09:30  读当天的数学推导（论文 / 笔记）
09:30 - 12:00  写 Rust 实现
12:00 - 13:00  午饭休息
13:00 - 15:30  调试 + 单元测试（梯度验证）
15:30 - 16:30  整理代码，写注释
16:30 - 17:00  git push，预习明天内容
```

---

## 最低可交付版本

如果两周结束时没有全部完成，**最低标准是：前向传播跑通 + 反向传播至少验证过 matmul 和 softmax + 能跑一个训练循环。**

这三件事完成，你对 Transformer 的理解已经远超大多数"用过 PyTorch"的人。

Adam、多头 attention 的反向传播、完整训练可以标成 `🚧 TODO`，后续补完。做了 70% 但每行代码都清楚，远胜于做了 100% 但靠 ChatGPT 粘贴的。

---

## 最后

两周之后，不管 loss 降到多少，你会真正知道：

- attention 为什么需要 scale
- LayerNorm 的梯度为什么那么写
- Adam 为什么比 SGD 快
- Transformer 的 residual 连接在反向传播里起什么作用

这些问题，用 PyTorch 跑一百遍也不一定能回答出来。

这件事值得做，今天就开始。
