# Network Quality Tester

Network Quality Tester是一款用于评估两点间网络连接质量的工具，特别关注模拟P2P游戏联机时的网络行为。它支持TCP和UDP协议的测试，能够测量带宽、延迟、丢包、抖动等关键网络参数，并在测试完成后生成图表总结。

## 功能特性

-   **TCP/UDP 测试**: 支持对TCP和UDP连接进行独立的网络质量评估。
-   **参数可配置**:
    -   自定义 `tickrate` (每秒发包数)。
    -   自定义数据包大小。
    -   自定义测试持续时间。
    -   指定目标IP和端口。
-   **网络质量指标**:
    -   **带宽**: 测量有效数据传输速率。
    -   **延迟**: TCP单向延迟（服务器端记录），UDP RTT（客户端记录）。
    -   **丢包率**: UDP测试中通过ACK机制精确测量。TCP中通过序列号间隙推断。
    -   **乱序包**: 通过序列号检测。
    -   **抖动**: UDP RTT的抖动计算。
    -   **数据完整性**: 通过哈希校验每个数据包。
-   **异常捕获**: 记录连接错误、发送/接收错误、数据损坏等异常。
-   **数据存储**: 测试结果以JSON格式保存在 `results/` 目录下，文件名包含会话ID和时间戳。
-   **图表生成**:
    -   带宽随时间变化图 (服务器接收视角)。
    -   延迟分布直方图和箱线图 (UDP RTT 和服务器单向延迟)。
    -   关键统计数据的表格图像。
    -   图表保存在 `results/charts/` 目录下。

## 安装

项目依赖以下Python库：

-   `pandas`
-   `matplotlib`

可以通过pip安装它们：

```bash
pip install pandas matplotlib
```

## 使用方法

项目通过 `main.py` 脚本提供的命令行接口 (CLI) 进行操作。

### 1. 启动服务器

在作为测试目标的一端，首先启动服务器。

**TCP 服务器示例**:
```bash
python main.py server tcp -p 9999 -b 0.0.0.0
```
这会在所有网络接口的 `9999` 端口上启动一个TCP服务器。

**UDP 服务器示例**:
```bash
python main.py server udp -p 9998 -b 0.0.0.0
```
这会在所有网络接口的 `9998` 端口上启动一个UDP服务器。

服务器会持续运行，直到手动停止 (例如，通过 `Ctrl+C`)。

### 2. 运行客户端测试

在另一端，运行客户端测试。

**TCP 客户端测试示例**:
```bash
python main.py client tcp <服务器IP地址> -p 9999 -d 10 -s 1024 -r 50
```
参数说明:
-   `client tcp`: 指定运行TCP客户端测试。
-   `<服务器IP地址>`: 替换为实际服务器的IP地址。
-   `-p 9999`: (可选) 服务器端口，如果TCP服务器使用了不同端口。
-   `-d 10`: (可选) 测试持续10秒 (默认10秒)。
-   `-s 1024`: (可选) 每个包的负载大小为1024字节 (默认1024字节)。
-   `-r 50`: (可选) 每秒发送50个包 (默认10pps)。
-   `--session-id <自定义ID>`: (可选) 指定一个会话ID。

**UDP 客户端测试示例**:
```bash
python main.py client udp <服务器IP地址> -p 9998 -d 15 -s 512 -r 30 --udp-ack-timeout 0.2
```
参数说明:
-   `client udp`: 指定运行UDP客户端测试。
-   `<服务器IP地址>`: 替换为实际服务器的IP地址。
-   `-p 9998`: (可选) 服务器端口，如果UDP服务器使用了不同端口。
-   `--udp-ack-timeout 0.2`: (可选, UDP特定) 设置UDP ACK的超时时间为0.2秒 (默认0.2秒)。

客户端测试完成后，会在 `results/` 目录下生成一个JSON格式的结果文件。

### 3. 分析结果并生成图表

测试完成后，可以使用 `analyze` 模式来处理结果文件并生成图表。

**分析最近一次测试的结果**:
```bash
python main.py analyze
```
该命令会自动查找 `results/` 目录下最新的客户端和服务器结果文件（通过文件名中的会话ID进行匹配），并生成图表到 `results/charts/`。

**分析特定会话ID或文件**:
```bash
python main.py analyze <会话ID或文件名关键字>
```
例如，如果会话ID是 `sid_1672220768860`：
```bash
python main.py analyze sid_1672220768860
```
或者指定一个具体的文件路径：
```bash
python main.py analyze results/tcp_client_127_0_0_1_9999_sid_1672220768860_20231228_100608_860.json
```

生成的图表将保存在 `results/charts/` 目录中。

### CLI 参数概览

```
usage: main.py [-h] {client,server,analyze} ...

Network Quality Tester CLI.

Modes:
  {client,server,analyze}
                        Run mode: client, server, or analyze.
    client              Run in client mode to test network to a server.
    server              Run in server mode to listen for client tests.
    analyze             Analyze previously saved test results.

optional arguments:
  -h, --help            show this help message and exit
```

**Client Mode (`main.py client -h`)**:
```
usage: main.py client [-h] [-p PORT] [-d DURATION] [-s SIZE] [-r RATE] [--session-id SESSION_ID] [--udp-ack-timeout UDP_ACK_TIMEOUT] {tcp,udp} host

positional arguments:
  {tcp,udp}             Type of test (tcp or udp).
  host                  Target server IP or hostname.

optional arguments:
  -h, --help            show this help message and exit
  -p PORT, --port PORT  Target server port. (TCP default: 9999, UDP default: 9998)
  -d DURATION, --duration DURATION
                        Duration in seconds (default: 10).
  -s SIZE, --size SIZE  Payload size in bytes (default: 1024).
  -r RATE, --rate RATE  Packets per second (default: 10).
  --session-id SESSION_ID
                        Specify Session ID (default: auto).
  --udp-ack-timeout UDP_ACK_TIMEOUT
                        UDP ACK timeout in seconds (default: 0.2).
```

**Server Mode (`main.py server -h`)**:
```
usage: main.py server [-h] [-b BIND_IP] [-p PORT] {tcp,udp}

positional arguments:
  {tcp,udp}             Type of server (tcp or udp).

optional arguments:
  -h, --help            show this help message and exit
  -b BIND_IP, --bind-ip BIND_IP
                        IP to bind server to (default: 0.0.0.0).
  -p PORT, --port PORT  Port to bind server to. (TCP default: 9999, UDP default: 9998)
```

**Analyze Mode (`main.py analyze -h`)**:
```
usage: main.py analyze [-h] [target]

positional arguments:
  target      Optional: Session ID, path to a result file, or part of filename. If empty, analyzes latest.

optional arguments:
  -h, --help  show this help message and exit
```

## 项目结构

```
network_quality_tester/
├── main.py                 # CLI 入口脚本
├── results/                # 存储测试结果 (JSON) 和图表 (PNG)
│   ├── charts/             # 存储生成的图表
│   └── ... (json files)
├── src/                    # 源代码目录
│   ├── __init__.py
│   ├── analysis.py         # 数据分析与图表生成逻辑
│   ├── packet_handler.py   # 数据包结构定义与序列化
│   ├── tcp_client.py       # TCP 客户端实现
│   ├── tcp_server.py       # TCP 服务器实现
│   ├── udp_client.py       # UDP 客户端实现
│   ├── udp_server.py       # UDP 服务器实现
│   └── utils.py            # 通用辅助函数 (如保存结果)
├── tests/                  # (可选) 单元测试和集成测试
└── README.md               # 本文档
```

## 输出示例

-   **JSON 结果文件**: 客户端和服务器的测试运行会生成详细的JSON文件，记录所有配置参数、统计数据、事件列表以及（对于服务器）每个接收到的数据包的详细信息。
-   **图表**: `analyze` 模式会生成PNG格式的图表，例如：
    -   `client_udp_rtt_dist_<sid>.png`: UDP客户端记录的RTT延迟分布图。
    -   `server_rx_payload_bw_<sid>_<client_addr>.png`: 服务器记录的接收带宽时序图。
    -   `server_oneway_latency_dist_<sid>_<client_addr>.png`: 服务器记录的单向延迟分布图。
    -   `client_summary_<sid>.png` / `server_summary_<sid>_<client_addr>.png`: 关键统计数据的文本表格图。

## (可选) 未来工作
-   支持在指定范围内随机化数据包大小。
-   更细粒度的客户端带宽随时间变化图。
-   双向测试模式。
-   生成集成的HTML测试报告。
-   更完善的单元测试和集成测试。
```
