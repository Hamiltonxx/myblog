**用 ndarray 从零实现能训练的 Transformer，完整前向+反向传播**。每天 6 小时，这个强度可以做得很扎实。

---

## 项目定位

对标 `llm.c`，但是 Rust 版，且自己实现反向传播（不依赖 autograd）。训练目标用**字符级语言模型**（char-level LM）——数据简单，能快速看到模型在学东西，成就感强。

最终产物：给它喂莎士比亚文本，它能生成风格相近的句子。经典验证场景，Karpathy 用过，效果直观。

---

## 里程碑计划（14天）

**第 1-2 天：地基——Tensor 操作层**

从零实现矩阵运算，不是为了造轮子，是为了后面反向传播时知道每个操作的梯度怎么算。

```
实现：matmul / transpose / broadcast_add / softmax
验证：和 numpy 结果对比（写 Python 对照脚本）
```

**第 3 天：Embedding + Positional Encoding**

```
实现：token embedding 查表 / 正弦位置编码
验证：给定 token id 序列，输出正确 shape 的向量
```

**第 4-5 天：单头 Attention 前向**

这是核心，要把公式和代码完全对应起来。

```
实现：Q K V 线性投影 / QK^T / scale / softmax / × V
验证：手算一个 2×2 的例子，和代码输出对齐
```

**第 6 天：Multi-Head Attention + Causal Mask**

```
实现：split heads / 并行 attention / concat / 输出投影
实现：上三角 mask（让位置 t 看不到 t+1 之后）
```

**第 7 天：FFN + LayerNorm + 残差**

```
实现：两层线性 + ReLU / LayerNorm（均值方差归一化）/ 残差连接
验证：单个 block 前向跑通
```

**第 8 天：完整前向 + 采样**

```
组装：N 个 block 堆叠 / 输出 logits / softmax 采样
验证：随机初始化权重，能生成（乱的）文字就算过
```

**第 9-10 天：反向传播——最硬的部分**

手动推导并实现每个操作的梯度。建议顺序：

```
matmul 梯度 → softmax 梯度 → attention 梯度 → layernorm 梯度
每个都写单元测试：用数值梯度检验（finite difference）验证
```

**第 11 天：SGD + 训练循环**

```
实现：cross-entropy loss / SGD（先不用 Adam）
跑通：loss 能下降就对了
```

**第 12 天：Adam 优化器**

```
实现：一阶矩 / 二阶矩 / bias correction
替换 SGD，loss 下降明显变快
```

**第 13 天：训练莎士比亚数据集**

```
数据：直接用 tinyshakespeare（~1MB 文本）
跑：loss 从 ~4.0 降到 ~1.5 左右说明模型在学
生成：看看输出像不像莎士比亚
```

**第 14 天：整理 + 写文章**

```
README 配架构图
每个模块写注释解释为什么这么实现
发 blog.cirray.cn / V2EX / Reddit
```

---

## 项目结构

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

---

## 关键依赖

```toml
[dependencies]
ndarray = { version = "0.16", features = ["rayon"] }  # 矩阵运算
rand = "0.8"       # 权重初始化
serde_json = "1"   # 可选，保存权重
```

就这三个，没有 ML 框架。

---

## 第一天从哪里开始

从 `tensor.rs` 的 `matmul` 开始，写完就用数值验证：

```rust
// 目标：实现这个，然后验证梯度
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

**每个操作都这样：先实现前向，立刻写反向，立刻用 finite difference 验证。** 不要攒到最后一起调，那时候根本不知道错在哪。

