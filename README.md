# bond-calendar-notify 📱

每天查询东方财富可转债日历，并通过 Server 酱推送两类提醒：

1. **今日可申购新债**：提醒在交易时间内通过券商 App 申购。
2. **今日公布中签结果**：提醒打开券商 App 查询中签结果；若中签，确保账户有足额认购资金。

两个事件若同日出现，会合并为一条 Server 酱消息，避免重复打扰。项目不保存证券账户信息，也不会读取券商账户。

## 推荐部署：VPS 定时运行

GitHub Actions 的 `schedule` 可能延迟，不适合盘前提醒。建议将本项目部署到 VPS，由 VPS 的 cron 在北京时间 09:10 的工作日执行。

以下命令以 Ubuntu / Debian VPS 为例。先通过 SSH 登录 VPS：

```bash
sudo timedatectl set-timezone Asia/Shanghai
sudo apt update
sudo apt install -y git python3 python3-venv
sudo mkdir -p /opt/bond-calendar-notify
sudo chown "$USER":"$USER" /opt/bond-calendar-notify
git clone https://github.com/penp112215-dotcom/bond-calendar-notify.git /opt/bond-calendar-notify
cd /opt/bond-calendar-notify
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --requirement requirements.txt
```

在项目目录创建只允许自己读取的环境变量文件：

```bash
cd /opt/bond-calendar-notify
printf 'SERVERCHAN_API_KEY=你的Server酱SendKey\n' > .env
chmod 600 .env
mkdir -p logs
```

先做一次不发送通知的验证：

```bash
cd /opt/bond-calendar-notify
.venv/bin/python -m unittest discover --start-directory tests --verbose
.venv/bin/python bonds.py --dry-run
```

最后执行 `crontab -e`，加入下面一行。它会在每个工作日北京时间 09:10 运行，并将日志写入项目目录：

```cron
10 9 * * 1-5 cd /opt/bond-calendar-notify && set -a && . ./.env && set +a && .venv/bin/python bonds.py >> logs/cron.log 2>&1
```

保存后用下面命令确认：

```bash
crontab -l
tail -f /opt/bond-calendar-notify/logs/cron.log
```

> VPS 启用 cron 后，请在 GitHub 仓库的 `Actions` 页面禁用 `push_bonds_daily` 工作流，避免 GitHub 和 VPS 产生重复通知。

## 数据字段与提醒日期

- `PUBLIC_START_DATE`：可申购日期。
- `BOND_START_DATE`：东方财富日历中的认购开始日期，通常对应可转债中签结果公布和认购资金准备的 T+2 日。

项目直接使用这两个日期字段，不自行推算交易日，因此可避免周末和法定休市造成的日期偏差。

## GitHub Actions（仅作备用）

`.github/workflows/push_daily_bonds.yml` 仍可手动运行或作为备用，但不建议依赖其准点性。配置 `SERVERCHAN_API_KEY` 为 Repository secret 后，可在 `Actions → push_bonds_daily → Run workflow` 手动测试。

## 本地验证

需要 Python 3.9 或更高版本：

```bash
python -m pip install --requirement requirements.txt
python -m unittest discover --start-directory tests --verbose
python bonds.py --dry-run
```

`--dry-run` 会调用真实数据源并显示当天两类事件，但不会发送 Server 酱通知，也不需要配置 SendKey。

默认没有任何事件时不推送。需要每日收到确认消息时，设置环境变量：

```bash
NOTIFY_WHEN_EMPTY=true
```

## 故障排查

- **没有收到提醒**：先检查 `logs/cron.log`，再确认 `.env` 中的 `SERVERCHAN_API_KEY` 正确。
- **脚本找不到模块**：确认 cron 使用的是 `.venv/bin/python`，而不是系统 Python。
- **部署后重复提醒**：禁用 GitHub 上的 `push_bonds_daily` 定时工作流。
- **数据源或 Server 酱失败**：脚本会以非零状态退出，错误会记录在 `logs/cron.log`。
