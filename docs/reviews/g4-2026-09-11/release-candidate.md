# G4 本地候选清单

日期：2026-09-11。候选标识：`g4-local-20260911`。这是供复核的本地工作树制品，不是正式 1.0 发布；包元数据保留 `0.6.0`。基准提交为 `86ebcc4b570f8b5b5acf3f1c6ba0f70ac7ed42f7`，包含未提交的 G1–G4 实现，不能只凭该 Git SHA 重建候选。

## 制品身份

目录：`backend/data/g4-rc-20260911/`。制品尚未上传 registry 或对外分发。校验使用 `shasum -a 256`；SHA-256 标识当前文件字节，不承诺重新构建得到相同归档时间戳。

| 制品 | SHA-256 |
| --- | --- |
| `extrio_backend-0.6.0.tar.gz` | `93bf8800957a3c5db21ee6fb9aab2d84c78732d0b632d61f6db1901fe8f1c5c5` |
| `extrio_backend-0.6.0-py3-none-any.whl` | `9110974f3a2f0e480b63d3749370848c7c3cde86bd3f2db2f260115fc708d5ce` |
| `extrio-web-g4-local.tar.gz` | `f46398235e74dfce8d020612b292d51982d89219b6d136453b21b783441a694a` |

Python 制品由 `uv build --project backend --out-dir backend/data/g4-rc-20260911` 生成（输出路径按运行目录解析）。Web 制品为通过 `pnpm --dir web build` 的 `web/dist` 归档。自包含 wheel 中包含合同、迁移、LICENSE 与 NOTICE，不包含实例数据与 `.env`。旧备份、登录材料、真实密钥和浏览器会话不属于发布制品。

Docker 双数据库安装验证通过。最终本地镜像 ID（`docker image inspect`）如下；可变的 `g4-rc-local` tag 本身不是发布身份。镜像仅存本机，没有推送 registry，下面的 ID 不是可从公共 registry 拉取的承诺。目标仅为本机 Linux ARM64 Docker，不代表已构建或验收 AMD64。

| 本地镜像 | 不可变 ID |
| --- | --- |
| `extrio/backend:g4-rc-local` | `sha256:036be8959da512c7867800027e38ddc3fbeaf8c1c4c134898b0ee108a0dae213` |
| `extrio/web:g4-rc-local` | `sha256:9139202baffa85e6b2eff978a5af04d995efe424fef4e08a2fb2b614196e5450` |

`scripts/verify-compose.sh` 分别使用 `extrio-e2e-g4-pg-final-20260911`（18338/18398）与 `extrio-e2e-g4-sqlite-final-20260911`（18328/18388）创建空环境。两次 exit 0，API/Worker/Web 全部 healthy；验证 readiness、未登录 401、首次管理员创建、鉴权读取、Web 入口与注销后 401。脚本已清理自身容器、网络和测试卷。SQLite 构建复用相同应用层缓存；manifest 的构建 provenance 可变化，清单记录最后一次本地结果。

## 验证状态

| 项目 | 状态 |
| --- | --- |
| 后端全量 | 504 passed，616.79 秒，无跳过；含独立 PostgreSQL |
| 前端全量 | 177 passed，36 文件；lint/API 生成/build 通过 |
| 升级与匹配旧版本恢复 | SQLite/PG 均通过，真实基准旧代码，空目标恢复 |
| 有鉴权浏览器集成 | 两库均通过，真实 API/Worker/HTTP 与合成 HTTPS 模型协议 |
| 桌面中英文 | 80 次页面测量、无页面异常和横向溢出；基础焦点/错误恢复通过 |
| 打包 | sdist → wheel → 仓库外合同/Store 初始化通过 |
| Docker 双数据库安装 | 两种 Compose 均通过；独立容器/卷已清理 |
| P28 真实模型 | Pending，本次外站/模型调用待确认 |
| P31 完整持续观测 | Pending；用户要求单实例，观测于 2026-09-11 10:56 停止，约 14.5 小时，需另行批准完整新窗口 |
| 产品签收、正式发布 | 未授权，未执行 |

## 回滚与签收

上线前需按 [运行手册](../../self-hosted-operations.md) 备份完整实例，并保留与备份匹配的应用制品、配置及密钥。失败回退恢复到空目标并重新验证，不运行破坏性的原地降级；本包只在独立测试库演练。

P27/P29/P30 的本地工程证据可复核；P32 的最终发布条件依赖 P28/P31 与用户签收。待证据齐备后再决定版本号、commit/tag、镜像分发与部署，不能把本清单视作执行这些操作的授权。当前 [技术复核](review.md) 和 [验证证据](validation.md) 与未完成门槛应一并交接。
