# surgo

**Open-source A-share multi-agent LLM research framework.**
开源的 A 股多智能体大模型研究框架。

surgo orchestrates a team of specialized LLM agents — analysts, researchers,
a trader, and a risk-management desk — that debate and collaborate to produce
a structured research read on Chinese A-share stocks. It is built for learning
and research. **It is not investment advice.**

> ⚠️ 本项目仅供学习与研究使用，所有 AI 生成内容不构成投资建议。

---

## Status / 当前状态

Early scaffold. The multi-agent engine is vendored and runnable; A-share data
adapters are being ported in (see [`docs/porting-plan.md`](docs/porting-plan.md)).

早期脚手架阶段。多智能体引擎已 vendor 进来且可运行；A 股数据适配层正在移植中。

## Lineage / 血统

surgo stands on two open-source projects, both Apache-2.0 licensed:

- **[TradingAgents](https://github.com/TauricResearch/TradingAgents)** by
  Tauric Research — the multi-agent trading framework that surgo's engine is
  derived from. ([arXiv:2412.20138](https://arxiv.org/abs/2412.20138))
- **[TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN)** by
  hsliuping and contributors — whose Apache-2.0 open-source engine informs
  surgo's A-share market adaptation. Only its Apache-2.0 components are used;
  its proprietary `app/` / `frontend/` / `core/` components are **not** used.

See [`NOTICE`](NOTICE) for the full attribution statement. surgo is an
independent project, not affiliated with or endorsed by either upstream.

## Layout / 目录结构

```
surgo/
├── tradingagents/        # vendored multi-agent engine (from TradingAgents)
├── cli/                  # command-line entry (`surgo` command)
├── main.py               # example programmatic entrypoint
├── docs/
│   └── porting-plan.md   # A-share data-layer porting roadmap
├── pyproject.toml
├── LICENSE               # Apache-2.0 (surgo contributors)
├── NOTICE                # upstream lineage & attribution
└── LICENSE.upstream-tradingagents
```

## Install / 安装

```bash
git clone https://github.com/openAgi2/surgo.git
cd surgo
python -m venv env
source env/bin/activate          # Windows: env\Scripts\activate
pip install -e .
```

## Quick start / 快速开始

```bash
# configure your LLM provider keys first (see .env handling in the engine)
surgo --ticker 600519 --date 2026-10-01
```

> Note: until the A-share data adapters land, the engine's default data
> vendors are US-oriented. A-share support is the active milestone.

## License / 许可

[Apache-2.0](LICENSE). Copyright 2026 surgo contributors.
Upstream attributions are in [`NOTICE`](NOTICE).
