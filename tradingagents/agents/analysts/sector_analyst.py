"""Sector analyst: A-share industry-board analysis.

Pre-fetches the stock's sector classification, sector-level performance,
and sector index history, injects them into the prompt, and has the LLM
write a sector-rotation and peer-comparison report without tool calls —
the same self-contained pattern the index and sentiment analysts use.
Returns a ``sector_report`` that the researchers can cite.

Only produces data for A-share symbols; for other instruments it
returns a not-applicable sentinel.
"""

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.context import get_instrument_context_from_state, get_language_instruction
from tradingagents.dataflows.vendors.ashare.sectors import get_sector_info
from tradingagents.dataflows.vendors.ashare.symbols import is_ashare


def create_sector_analyst(llm):
    """Create a sector analyst node for A-share industry-board analysis."""

    def sector_analyst_node(state):
        ticker = state["company_of_interest"]
        trade_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        # Pre-fetch sector data (returns sentinel for non-A-share)
        sector_data = get_sector_info(ticker, trade_date)

        system_message = _build_system_message(
            ticker=ticker,
            trade_date=trade_date,
            sector_data=sector_data,
            is_ashare=is_ashare(ticker),
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Report what your data supports; another agent decides the trade."
                    " Today's date is {current_date}; treat it as 'now' for all analysis."
                    " {instrument_context}"
                    " Do not call external tools; all data is already in this prompt."
                    "\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=trade_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        formatted_messages = prompt.format_messages(messages=state["messages"])
        result = llm.invoke(formatted_messages)

        return {
            "messages": [AIMessage(content=result.content)],
            "sector_report": result.content,
        }

    return sector_analyst_node


def _build_system_message(
    *,
    ticker: str,
    trade_date: str,
    sector_data: str,
    is_ashare: bool,
) -> str:
    """Assemble the sector-analyst system message with structured data blocks."""

    if not is_ashare:
        return (
            f"You are an industry/sector analyst. The instrument `{ticker}` is not an "
            f"A-share stock, so A-share sector data does not apply. State briefly that "
            f"no A-share sector analysis is available for this instrument, and that "
            f"the single-stock analysts' reports should be consulted instead."
        )

    return f"""You are a professional A-share sector/industry analyst specializing in sector rotation and peer comparison. Your task is to produce a sector analysis report for {ticker} as of {trade_date}, drawing on the pre-fetched sector data below.

## Sector Data (pre-fetched)

<start_of_sector_data>
{sector_data}
<end_of_sector_data>

## How to analyze this data

1. **Sector identification.** Confirm which THS industry board the stock belongs to. If the sector was not identified, say so and skip the rest — do not fabricate a sector assignment.

2. **Sector performance.** Analyze the sector snapshot: the board's recent change, rank among all 90 THS boards, and net capital flow. Is the sector hot (top-ranked, positive flow) or cold (bottom-ranked, negative flow)?

3. **Sector trend.** If sector index OHLCV data is available, assess the trend over the recent sessions: direction, momentum, and any notable pattern (e.g., breakout from range, reversal signal).

4. **Sector rotation context.** Where does this sector sit in the current rotation cycle? A-shares have pronounced sector-rotation dynamics driven by policy, capital flows, and thematic narratives. If data permits, comment on whether the sector appears to be in an accumulation, momentum, or distribution phase.

5. **Peer comparison.** If the sector snapshot includes aggregate valuation metrics or capital-flow data, use them to contextualize the stock's position within its industry. Note whether the sector overall is expensive or cheap relative to history (if the data allows).

6. **Be honest about data limits.** If sector identification failed, or if some data blocks are unavailable, flag this explicitly. Base conclusions only on what is present.

## Output

Write a focused sector analysis report. Include:

- Sector membership and current performance
- Sector trend assessment
- Sector rotation positioning
- Relevance of sector dynamics to the target stock

Append a Markdown summary table with key sector indicators.

{get_language_instruction()}"""
