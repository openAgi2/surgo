"""Index analyst: A-share broad-market context.

Pre-fetches major index data and sector-level snapshots, injects them
into the prompt, and has the LLM write a market-environment report
without tool calls — the same self-contained pattern the sentiment
analyst uses.  Returns an ``index_report`` that the researchers can
cite alongside the single-stock analyst reports.

Only produces data for A-share symbols; for other instruments it
returns a not-applicable sentinel.
"""

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.context import get_instrument_context_from_state, get_language_instruction
from tradingagents.dataflows.vendors.ashare.overview import get_market_overview
from tradingagents.dataflows.vendors.ashare.symbols import is_ashare


def create_index_analyst(llm):
    """Create an index analyst node for A-share market context."""

    def index_analyst_node(state):
        ticker = state["company_of_interest"]
        trade_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        # Pre-fetch market overview data (returns sentinel for non-A-share)
        market_data = get_market_overview(ticker, trade_date)

        system_message = _build_system_message(
            ticker=ticker,
            trade_date=trade_date,
            market_data=market_data,
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
            "index_report": result.content,
        }

    return index_analyst_node


def _build_system_message(
    *,
    ticker: str,
    trade_date: str,
    market_data: str,
    is_ashare: bool,
) -> str:
    """Assemble the index-analyst system message with structured data blocks."""

    if not is_ashare:
        return (
            f"You are a broad-market analyst. The instrument `{ticker}` is not an "
            f"A-share stock, so A-share index and sector data does not apply. "
            f"State briefly that no A-share market overview is available for this "
            f"instrument, and that the single-stock analysts' reports should be "
            f"consulted instead."
        )

    return f"""You are a professional A-share market analyst specializing in broad-market context and systemic risk assessment. Your task is to produce a concise market-environment report for {ticker} as of {trade_date}, drawing on the pre-fetched market data below.

## Market Data (pre-fetched)

<start_of_market_data>
{market_data}
<end_of_market_data>

## How to analyze this data

1. **Index trend assessment.** Read the major index levels and percentage changes. Are the Shanghai, Shenzhen, and ChiNext indices trending up, down, or sideways? Note any divergences between them (e.g., Shanghai up but ChiNext down suggests large-cap strength vs small-cap weakness).

2. **Sector snapshot.** Use the THS industry board data to identify the hottest and coldest sectors. Which sectors are leading? Which are lagging? Note any concentration risk (a few sectors driving the market) vs broad participation.

3. **Market environment summary.** Synthesize the index and sector data into a market-environment classification:
   - Trend: up / down / range-bound
   - Breadth: broad participation / narrow leadership
   - Risk level: low / medium / high (based on index drawdowns and sector dispersion)

4. **Relevance to the target stock.** Briefly note how the broad-market context affects the stock under analysis. For example, if the market is in a risk-off phase, even strong individual stories may face headwinds.

5. **Be honest about data limits.** If any data block shows "unavailable" or missing values, flag this and base conclusions only on what is actually present.

## Output

Write a focused market-environment report. Append a Markdown summary table of key indicators (index, level, 5D change, 20D change, assessment).

{get_language_instruction()}"""
