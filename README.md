# Telco-DE-GenBI — Chat với dữ liệu qua Cube (semantic layer)

Hỏi đáp dữ liệu bằng tiếng Việt/Anh, có trí nhớ hội thoại, trả về **bảng + biểu đồ**. Mọi con số đều đi qua
**semantic layer (Cube Core)** — LLM không tự viết SQL, chỉ chọn measure/dimension đã định nghĩa sẵn.

Dataset demo: **Kaggle Superstore** (chuỗi bán lẻ Mỹ, 9.994 order line, 2014–2017, USD).

## Mục lục
1. [Kiến trúc](#1-kiến-trúc)
2. [Yêu cầu](#2-yêu-cầu)
3. [Cài đặt từng bước](#3-cài-đặt-từng-bước)
4. [Dùng ứng dụng](#4-dùng-ứng-dụng)
5. [Cổng & thông tin đăng nhập](#5-cổng--thông-tin-đăng-nhập)
6. [Cấu trúc thư mục](#6-cấu-trúc-thư-mục)
7. [Cấu hình (.env)](#7-cấu-hình-env)
8. [Trí nhớ của agent](#8-trí-nhớ-của-agent)
9. [Đổi LLM](#9-đổi-llm)
10. [Đo chất lượng (evals)](#10-đo-chất-lượng-evals)
11. [Xử lý sự cố](#11-xử-lý-sự-cố)
12. [Lưu ý đã biết & lộ trình](#12-lưu-ý-đã-biết--lộ-trình)

---

## 1. Kiến trúc

```
 Kaggle (Superstore CSV) ── kagglehub
        │
        ▼   Airflow DAG `superstore_etl`
 ┌──────────────────────────────────────────────────────────────────────┐
 │ task 1  download_superstore_to_s3  → RustFS s3://lakehouse/raw/...   │  bronze (CSV thô)
 │ task 2  dbt build (airflow/dbt/sale) → silver → gold (Delta Lake)    │
 └──────────────────────────────────────────────────────────────────────┘
        ▼
 Trino  ── catalog `hive`  : bronze  (external table đọc CSV)
        └─ catalog `delta` : silver / gold   (metadata qua Hive Metastore, data trên RustFS)
        ▼
 Cube Core  (cube/model: cubes/sales.yml + views/superstore_sales.yml, pre-aggregation)
        │  REST  :4000
        ▼
 Streamlit app (app/app.py) :8501 — UI + LangGraph agent chạy chung 1 process
        ├─ short-term memory: checkpointer theo thread (in-memory, hoặc Postgres)
        └─ long-term memory : store ghi chú theo user (thuật ngữ, ưu tiên)
```

| Thành phần | Vai trò |
|---|---|
| **RustFS** | Object storage tương thích S3 (data lake) |
| **Hive Metastore + Postgres** (`metastore-db`) | Metadata bảng; cũng chứa DB của Airflow và của agent |
| **Trino** | Query engine, 2 catalog `hive` (bronze) và `delta` (silver/gold) |
| **dbt (trong Airflow)** | Transform bronze → silver → gold |
| **Airflow** | Điều phối ETL (DAG `superstore_etl`, chạy tay) |
| **Cube** | Semantic layer + pre-aggregation (dev mode dùng Cube Store nhúng) |
| **Streamlit app** | Chat UI + agent LangGraph |
| **Spark + Jupyter** | Tuỳ chọn, để khám phá dữ liệu (`demo/test.ipynb`) |

---

## 2. Yêu cầu

- **Docker Desktop** (Compose v2), cấp **≥ 8 GB RAM** và ≥ 10 GB đĩa trống cho Docker (Trino 3 GB, Airflow ~3 GB, Spark, Cube…).
- **Python 3.12** + [**uv**](https://docs.astral.sh/uv/) — chỉ cần nếu chạy app/evals trên máy (không dùng container).
- **API key của LLM** (mặc định OpenAI). Dataset Kaggle là public, không cần key Kaggle.
- Mac M-series: image `apache/hive` chạy được nhưng có thể chậm hơn nếu bị emulate amd64.

---

## 3. Cài đặt từng bước

> Tất cả lệnh chạy ở thư mục gốc của repo.

### Bước 1 — Tạo file `.env`

```bash
cp .env.example .env
```

Mở `.env` và điền tối thiểu:

| Biến | Cách điền |
|---|---|
| `OPENAI_API_KEY` | Key OpenAI của bạn (hoặc đổi LLM, xem [mục 9](#9-đổi-llm)) |
| `CUBEJS_API_SECRET` | Chuỗi bất kỳ, **≥ 32 ký tự** để tránh warning `InsecureKeyLengthWarning` |
| `FERNET_KEY` | Bắt buộc cho Airflow. Sinh bằng: `python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` |
| `_AIRFLOW_WWW_USER_PASSWORD` | Mật khẩu đăng nhập Airflow UI |

Các biến còn lại (S3, Cube, Airflow UID…) có sẵn giá trị mặc định dùng được cho local.
Chi tiết ở [mục 7](#7-cấu-hình-env).

> ⚠️ `.env` đã được `.gitignore`. **Không commit key thật.** Nếu bạn từng commit `.env` trước đây
> (history có commit "stop tracking .env"), hãy **rotate** các key đã lộ.

### Bước 2 — Dựng stack dữ liệu

```bash
docker compose up -d --build
```

Lệnh này chạy: Spark (master/worker + Jupyter), RustFS, Postgres (`metastore-db`), Hive Metastore,
Trino, Cube và container `genbi` (Streamlit). Nó cũng tạo mạng Docker `data-platform-net`
mà Airflow sẽ dùng chung.

Chờ ~1–2 phút cho tới khi Trino `healthy`:

```bash
docker compose ps
docker compose exec trino trino --execute "SELECT count(*) FROM tpch.tiny.orders"   # smoke test → 15000
```

> Lúc này app đã lên ở http://localhost:8501 nhưng **chưa có dữ liệu** — làm tiếp bước 3–4.

### Bước 3 — Dựng Airflow

Airflow nằm trong compose riêng và dùng chung mạng + Postgres của bước 2, nên **phải chạy bước 2 trước**.

```bash
docker compose -f docker-compose-airflow.yaml up -d --build
```

Lần đầu service `airflow-init` sẽ migrate DB và tạo user (theo `_AIRFLOW_WWW_USER_*` trong `.env`).
Khi apiserver `healthy`, mở http://localhost:8090 và đăng nhập.

> Nếu lỗi kết nối DB `airflow`: DB này chỉ được tạo khi volume Postgres còn trống. Với volume cũ, tạo tay:
> ```bash
> docker exec -i metastore-db psql -U hive -d hive < initdb/01-agent.sql
> docker exec -i metastore-db psql -U hive -d hive < initdb/02-airflow.sql
> ```

### Bước 4 — Nạp dữ liệu (chạy ETL)

Trong Airflow UI:

1. Tìm DAG **`superstore_etl`** → bấm **Unpause** (DAG tạo ra ở trạng thái pause).
2. Bấm **Trigger**. DAG gồm 2 task:
   - `download_superstore_to_s3`: tải CSV từ Kaggle, đổi Windows-1252 → UTF-8, đẩy lên `s3://lakehouse/raw/superstore/superstore.csv`.
   - `dbt_build_silver_gold`: `dbt deps` + `dbt build` → tạo external table bronze, `silver.superstore_orders`, `gold.sales` (kèm test).

Hoặc dùng CLI:

```bash
docker compose -f docker-compose-airflow.yaml exec airflow-scheduler airflow dags unpause superstore_etl
docker compose -f docker-compose-airflow.yaml exec airflow-scheduler airflow dags trigger superstore_etl
```

Kiểm tra kết quả — phải ra **9994**:

```bash
docker compose exec trino trino --execute "SELECT count(*) FROM delta.gold.sales"
```

<details>
<summary>Không muốn dùng Airflow? Nạp thủ công</summary>

```bash
# 1) Đẩy CSV lên RustFS (từ máy host)
uv pip install boto3 kagglehub
S3_ENDPOINT=http://localhost:9000 uv run python airflow/dags/download_superstore.py

# 2) Chạy dbt từ máy host (Trino expose ở localhost:8085)
uv pip install dbt-trino
cd airflow/dbt/sale
export DBT_TARGET=dev DBT_PROFILES_DIR=.
dbt deps
dbt build --vars '{"lake_root": "s3://lakehouse", "raw_superstore_location": "s3://lakehouse/raw/superstore"}'
```
</details>

### Bước 5 — Kiểm tra Cube

Mở http://localhost:4000 (Playground, dev mode). Chọn view **`superstore_sales`**, thử measure
`total_sales` + dimension `region`. Lần query đầu có thể chậm vì Cube build pre-aggregation
`daily_by_geo_category`; các lần sau nhanh hơn.

Hoặc kiểm tra qua log: `docker compose logs -f cube`.

### Bước 6 — Mở ứng dụng chat

http://localhost:8501 → hỏi thử: *"Vùng nào có doanh thu cao nhất năm 2017?"*

#### Chạy app trên máy thay vì container (tiện debug)

```bash
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -r app/requirements.txt
# .env dùng CUBE_API_URL=http://localhost:4000/cubejs-api/v1 (đã là mặc định)
streamlit run app/app.py
```

Nếu chạy local thì có thể tắt container `genbi` để khỏi trùng cổng 8501: `docker compose stop genbi`.

---

## 4. Dùng ứng dụng

- **Hỏi tự nhiên**: *"Vẽ xu hướng doanh thu theo tháng"*, *"Biên lợi nhuận theo ngành hàng và phân khúc"*,
  *"Top 10 sản phẩm lỗ nhiều nhất"*.
- Mỗi câu trả lời có: lời giải thích, **biểu đồ** (line/bar tuỳ dạng dữ liệu), **bảng** và expander
  **"Cube query / SQL"** để kiểm tra agent đã hỏi gì.
- Hỏi nối tiếp được ("còn riêng bang California thì sao?") vì agent nhớ theo thread.
- Sidebar: ô **User** (định danh cho trí nhớ dài hạn) và nút **Hội thoại mới** (tạo thread mới).
- Dạy agent thuật ngữ: *"Từ giờ 'doanh thu' là total_sales, nhớ giúp tôi"* → lưu vào long-term memory.

---

## 5. Cổng & thông tin đăng nhập

| Dịch vụ | URL / cổng | Đăng nhập |
|---|---|---|
| GenBI chat (Streamlit) | http://localhost:8501 | — |
| Cube Playground | http://localhost:4000 | — (dev mode) |
| Cube SQL API (Postgres wire) | `localhost:15432` | `cube` / `cube` (đổi qua `CUBE_SQL_*`) |
| Airflow | http://localhost:8090 | `_AIRFLOW_WWW_USER_USERNAME` / `_PASSWORD` trong `.env` |
| Trino UI | http://localhost:8085 | user bất kỳ (không bật auth) |
| RustFS console | http://localhost:9001 | `rustfsadmin` / `rustfsadmin` |
| RustFS S3 API | http://localhost:9000 | key `S3_ACCESS_KEY` / `S3_SECRET_KEY` |
| Spark master UI | http://localhost:8080 | — |
| Jupyter Lab | http://localhost:8888 | token xem ở `docker compose logs spark-master` |
| Postgres (`metastore-db`) | `localhost:5432` | `hive`/`hive` (DB `hive`), `agent`/`agent`, `airflow`/`airflow` |
| Hive Metastore (thrift) | `localhost:9083` | — |

Xem query đang/đã chạy trên Trino: http://localhost:8085 (tab Query History) hoặc
`docker compose exec trino trino --execute "SELECT query_id, state, query FROM system.runtime.queries ORDER BY created DESC LIMIT 10"`.

---

## 6. Cấu trúc thư mục

```
app/                      Streamlit app (UI + agent)
  app.py                  giao diện chat, bảng, biểu đồ
  agent.py                LangGraph agent, tool, trí nhớ ngắn/dài hạn
  cube_client.py          gọi Cube REST (JWT ký bằng CUBEJS_API_SECRET)
  prompts.py              system prompt
  Dockerfile, requirements.txt
cube/model/               semantic layer
  cubes/sales.yml           measures, dimensions, pre-aggregation
  views/superstore_sales.yml  bề mặt duy nhất agent được thấy
airflow/
  dags/                   superstore_etl.py, download_superstore.py
  dbt/sale/               dbt project (bronze → silver → gold) — xem README riêng
  Dockerfile              Airflow + dbt venv + kagglehub, boto3
trino/catalog/            hive.properties (bronze), delta.properties (silver/gold), tpch
hive-metastore/           core-site.xml (cấu hình S3A cho HMS và Spark)
initdb/                   tạo DB `agent` và `airflow` trong Postgres (chỉ chạy lần đầu)
data_platform/rustfs/     dữ liệu RustFS mount từ host
demo/                     notebook Spark/Jupyter
evals/                    golden_questions.yaml + run_evals.py
docker-compose.yml          stack dữ liệu + Cube + app
docker-compose-airflow.yaml Airflow (LocalExecutor), dùng chung mạng data-platform-net
```

### Mô hình dữ liệu

| Bảng | Grain | Ghi chú |
|---|---|---|
| `hive.bronze.superstore_raw` | dòng CSV | external table, mọi cột `varchar` |
| `delta.silver.superstore_orders` | order line | ép kiểu, parse ngày `M/D/YYYY`, dedup theo `row_id` |
| `delta.gold.sales` | order line | denormalized + `days_to_ship`; Cube đọc trực tiếp |

Vì sao 2 catalog? Delta connector không tạo được external table CSV, nên bronze dùng `hive`;
silver/gold dùng `delta` (hỗ trợ `CREATE OR REPLACE TABLE` cho dbt).

---

## 7. Cấu hình (.env)

| Nhóm | Biến | Mặc định / ghi chú |
|---|---|---|
| LLM | `LLM_MODEL` | `openai:gpt-4.1` (dạng `provider:model`) |
| | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | theo provider |
| | `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` |
| Cube | `CUBEJS_API_SECRET` | phải **trùng** giữa container `cube` và app; ≥ 32 ký tự |
| | `CUBE_API_URL` | local: `http://localhost:4000/cubejs-api/v1`; compose tự ghi đè thành `http://cube:4000/...` |
| | `CUBE_TIMEZONE` | `Asia/Singapore` |
| | `CUBE_SQL_USER` / `CUBE_SQL_PASSWORD` | `cube` / `cube` |
| Memory | `AGENT_DB_URI` | bỏ trống = in-memory; ví dụ `postgresql://agent:agent@localhost:5432/agent` |
| S3 | `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION` | RustFS: `http://rustfs:9000`, `rustfsadmin`, `us-east-1` |
| Airflow | `AIRFLOW_PROJ_DIR`, `AIRFLOW_UID`, `FERNET_KEY`, `_AIRFLOW_WWW_USER_*` | `FERNET_KEY` bắt buộc |
| Tracing | `LANGSMITH_*` | tuỳ chọn |

> Nếu đổi `S3_ACCESS_KEY`/`S3_SECRET_KEY`/endpoint, phải sửa **cả** `hive-metastore/core-site.xml`
> (Hive Metastore và Spark không đọc biến môi trường).

---

## 8. Trí nhớ của agent

- **Ngắn hạn**: mỗi `thread_id` lưu toàn bộ hội thoại. Mặc định in-memory (mất khi restart);
  đặt `AGENT_DB_URI` để lưu vào Postgres (DB `agent` đã được `initdb/01-agent.sql` tạo sẵn).
  Trong compose có thể bỏ comment dòng `AGENT_DB_URI` của service `genbi`
  (`postgresql://agent:agent@metastore-db:5432/agent`).
- **Dài hạn**: tool `save_user_note` / `recall_user_notes` lưu thuật ngữ và ưu tiên theo `user_id`
  (ô **User** ở sidebar).

---

## 9. Đổi LLM

Sửa `LLM_MODEL` trong `.env` (định dạng `provider:model` của LangChain) rồi restart app:

| Provider | Ví dụ | Key cần |
|---|---|---|
| OpenAI (mặc định) | `openai:gpt-4.1` | `OPENAI_API_KEY` |
| Anthropic | `anthropic:claude-sonnet-5-5` | `ANTHROPIC_API_KEY` |
| Azure OpenAI | `azure_openai:<deployment>` | biến Azure tương ứng |
| Ollama (chạy trên host) | `ollama:<model>` | `OLLAMA_BASE_URL` |

```bash
docker compose up -d --force-recreate genbi     # nếu chạy bằng container
```

---

## 10. Đo chất lượng (evals)

Golden set: `evals/golden_questions.yaml` — mỗi câu hỏi kèm các member Cube **bắt buộc** phải có trong query agent sinh ra.

```bash
source .venv/bin/activate
uv pip install -r app/requirements.txt pyyaml
python evals/run_evals.py
```

Cần Cube đang chạy và có dữ liệu. Đây là đo "query-shape accuracy" (đúng measure/dimension),
chưa so khớp giá trị số. Mỗi lần agent sai 2 lần cùng kiểu → thêm 1 case vào golden set.

---

## 11. Xử lý sự cố

| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| `StreamlitDuplicateElementId: plotly_chart` | Đã sửa bằng `key` duy nhất cho mỗi chart. Nếu còn gặp, kiểm tra bạn đang chạy bản `app/app.py` mới nhất và restart Streamlit. |
| `InsecureKeyLengthWarning` (JWT) | `CUBEJS_API_SECRET` < 32 ký tự. Vô hại khi dev; đặt secret dài hơn để hết warning (đổi ở cả `.env` và restart `cube`). |
| Cube lỗi `Table ... does not exist` | Chưa chạy ETL, hoặc `delta.gold.sales` chưa có. Chạy lại bước 4. |
| Airflow không lên / lỗi DB | Chạy bước 2 trước; kiểm tra `FERNET_KEY` đã điền; tạo DB `airflow` tay (xem bước 3). |
| `network data-platform-net not found` | Chưa chạy `docker compose up -d` (bước 2) trước Airflow. |
| dbt: `external_location` bị từ chối ở catalog `delta` | Đúng thiết kế: bronze phải ở catalog `hive` (var `bronze_catalog`). Đừng đổi catalog mặc định bronze sang `delta`. |
| Trino bị OOM / restart | Tăng RAM cho Docker Desktop; Trino bị giới hạn `mem_limit: 3g`. |
| Cổng 8501 / 8080 bị chiếm | Dừng tiến trình cũ (`lsof -i :8501`) hoặc đổi mapping cổng trong compose. |
| Query Cube đầu tiên rất chậm | Cube đang build pre-aggregation; chờ xong rồi hỏi lại. |
| App báo `Lỗi gọi agent` | Kiểm tra API key LLM, `CUBE_API_URL`, và `CUBEJS_API_SECRET` có trùng với container `cube` không. |
| Thay đổi `cube/model/*.yml` không có hiệu lực | Dev mode tự reload; nếu không, `docker compose restart cube`. |

Dọn sạch để làm lại từ đầu (⚠️ **xoá toàn bộ dữ liệu** của Postgres và Airflow):

```bash
docker compose -f docker-compose-airflow.yaml down -v
docker compose down -v
```

---

## 12. Lưu ý đã biết & lộ trình

**Lưu ý**
- Stack dùng cấu hình dev (`CUBEJS_DEV_MODE: "true"`, secret mặc định, Trino không auth) — **không dùng cho production**.
- CubeStore router/worker rời đang bị comment trong `docker-compose.yml`; dev mode dùng Cube Store nhúng là đủ.
  Chỉ cần bỏ comment khi scale ngang / lên production.
- Superset (BI) đang bị comment; muốn dùng thì bỏ comment service `superset`, đặt `SUPERSET_SECRET_KEY`, rồi thêm DB
  `postgresql://cube:cube@cube:15432/db`.
- `order_count`, `customer_count` (count distinct) không dùng được pre-aggregation → query trực tiếp Trino, chậm hơn.
- Nên pin phiên bản `CUBE_VERSION`, `TRINO_VERSION`, `RUSTFS_VERSION` khi đã chạy ổn (mặc định `latest`).

**Lộ trình**
1. Thay dataset Superstore bằng gold table thật — chỉ cần thêm cube + view.
2. Dashboard agent: tạo chart/dashboard Superset từ `results[].query`.
3. Row-level security: dùng `user_id` trong JWT + `queryRewrite` trong `cube/cube.js`.
4. Langfuse/LangSmith để trace từng lượt agent; mở rộng golden set lên 50–100 câu thật.
