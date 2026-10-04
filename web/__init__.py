"""surgo web UI: a Streamlit interface to the surgo trading-agents engine.

Ported from TradingAgents-CN's Apache-2.0-licensed ``web/`` component
(historical git revision ``5a143f44^``, later removed upstream), with the
multi-user infrastructure (login, permissions, Redis/MongoDB sessions) cut
and the engine seam re-pointed at surgo's ``TradingAgentsGraph``.

Copyright 2024-2026 hsliuping & TradingAgents-CN Contributors
Modifications for surgo: Copyright 2026 surgo contributors
SPDX-License-Identifier: Apache-2.0
"""
