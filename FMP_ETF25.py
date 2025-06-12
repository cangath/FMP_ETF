import streamlit as st
import pandas as pd
import requests # For making API calls to FMP
import datetime as dt
import time

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Custom ETF Analyzer (FMP)", layout="wide", initial_sidebar_state="expanded")
st.title("📈 Custom ETF Analyzer")
st.caption("Using Financial Modeling Prep End-of-Day Price Data")

# --- 2. YOUR INTRODUCTORY PARAGRAPH ---
# Replace the content of this st.markdown block with your desired paragraph.
# You can use Markdown formatting (like **bold**, *italics*, links [text](URL), etc.)
st.markdown("""
Welcome to the Custom ETF Analyzer! This tool demonstrates the construction and performance
tracking of a price-weighted ETF. It was inspired by practical exercises and portfolio analysis
from work with **Fresno State's Student Managed Investment Fund**. The primary goal is to visualize
how a custom basket of stocks would perform as an ETF and to explore the impact of constituent
selection and weighting methodologies. Here, we focus on a price-weighted approach and compare
its performance against standard market benchmarks.
""")
st.markdown("---")

# --- 3. FMP API Key Handling ---
FMP_API_KEY = None
try:
    FMP_API_KEY = st.secrets.get("FMP_API_KEY") # Use .get for graceful handling if not found
except (FileNotFoundError, KeyError): # FileNotFoundError for local, KeyError if key missing in deployed secrets
    # This error is mainly for local dev if secrets.toml is missing.
    # On cloud, if secret isn't set, FMP_API_KEY will be None.
    pass 

if not FMP_API_KEY:
    st.sidebar.error("`FMP_API_KEY` not found in Streamlit secrets. Please configure it for the app to fetch data.")
    st.error("CRITICAL: FMP API Key is not configured. Data fetching will fail. Please set it in Streamlit Cloud app settings under 'Secrets'.")
    st.stop()

# --- 4. DEFAULT TICKERS & BENCHMARK ETFs ---
# Magnificent 7 as default for custom ETF
MAG7_TICKERS_DEFAULT = ["AAPL", "MSFT", "GOOG", "AMZN", "NVDA", "META", "TSLA"]
DEFAULT_CUSTOM_TICKERS_STRING = ",".join(MAG7_TICKERS_DEFAULT)

BENCHMARK_ETFS = {
    "VOO": "S&P 500 (VOO)",
    "DIA": "Dow Jones Ind. Avg. (DIA)",
    "QQQ": "Nasdaq 100 (QQQ)"
}

# --- 5. CACHED DATA FETCHING FUNCTION (FMP - Time Series) ---
@st.cache_data(ttl="4h") # Cache EOD prices for 4 hours
def fetch_fmp_daily_prices(tickers_tuple, api_key_param, start_date_str, end_date_str):
    # This function will be called with all tickers to fetch (custom + benchmarks)
    if not api_key_param: # Should be caught earlier, but as a safeguard
        return {}, [], [("API_KEY_MISSING", "API Key missing in fetch function")]

    st.sidebar.info(f"♻️ Fetching EOD prices from FMP for: {', '.join(tickers_tuple)}...")
    _all_stock_close_prices = {}
    _successful_tickers = []
    _problematic_items = []
    base_url = "https://financialmodelingprep.com/api/v3/historical-price-full/"

    for i, ticker in enumerate(tickers_tuple):
        # Respect FMP rate limits - a small delay can help for many tickers
        if i > 0: time.sleep(0.25) # 250ms delay
        
        try:
            url = f"{base_url}{ticker}?from={start_date_str}&to={end_date_str}&apikey={api_key_param}"
            response = requests.get(url, timeout=20) # Increased timeout
            response.raise_for_status() # Raises HTTPError for bad responses (4XX or 5XX)
            data = response.json()

            if "historical" in data and data["historical"]:
                price_df = pd.DataFrame(data["historical"])
                price_df['date'] = pd.to_datetime(price_df['date'])
                price_df = price_df.set_index('date').sort_index(ascending=True)
                if 'close' in price_df.columns:
                    _all_stock_close_prices[ticker] = price_df['close'].astype(float)
                    _successful_tickers.append(ticker)
                else: _problematic_items.append((ticker, "FMP EOD: 'close' column not found."))
            elif "Error Message" in data: # FMP often returns errors in JSON with this key
                _problematic_items.append((ticker, f"FMP API Error: {data['Error Message']}"))
            else: # Other unexpected response
                _problematic_items.append((ticker, f"FMP EOD: No 'historical' data found or unexpected format for {ticker}."))
        except requests.exceptions.HTTPError as http_err:
            _problematic_items.append((ticker, f"FMP HTTP Error for {ticker}: {http_err} (Status: {response.status_code if 'response' in locals() else 'N/A'})"))
        except requests.exceptions.RequestException as req_err: # Other network errors
            _problematic_items.append((ticker, f"FMP Request Error for {ticker}: {req_err}"))
        except Exception as e: # Catch-all for other errors (e.g., JSON parsing)
            _problematic_items.append((ticker, f"FMP General Error for {ticker}: {e}"))
            
    return _all_stock_close_prices, _successful_tickers, _problematic_items

# --- 6. SIDEBAR FOR USER INPUTS ---
st.sidebar.header("🛠️ ETF Configuration")
raw_tickers_input = st.sidebar.text_area(
    "Custom ETF Stock Tickers (comma-separated)",
    DEFAULT_CUSTOM_TICKERS_STRING, # Default to Mag7
    height=100 # Adjusted height
)

default_start_date = dt.date.today() - dt.timedelta(days=365 * 5) # Default to 5 years
default_end_date = dt.date.today() - dt.timedelta(days=1) # Yesterday
start_date_input = st.sidebar.date_input("Start Date", default_start_date)
end_date_input = st.sidebar.date_input("End Date", default_end_date)

selected_benchmarks_for_overlay = st.sidebar.multiselect(
    "Compare Custom ETF With (on main performance chart):",
    options=list(BENCHMARK_ETFS.keys()),
    default=["VOO", "QQQ"], # Default benchmarks
    format_func=lambda x: BENCHMARK_ETFS[x]
)

st.sidebar.write("---")
if st.sidebar.button("Clear Price Data Cache & Rerun"):
    st.cache_data.clear()
    st.sidebar.success("Price data cache cleared! Rerunning...")
    st.rerun()

# --- 7. MAIN APP LOGIC ---
# Parse user's custom tickers
user_tickers_list = sorted(list(set(t.strip().upper() for t in raw_tickers_input.split(',') if t.strip())))

if not user_tickers_list:
    st.warning("Please enter at least one stock ticker for your custom ETF.")
    st.stop()

if start_date_input >= end_date_input:
    st.error("Error: Start date must be before end date.")
    st.stop()
if (end_date_input - start_date_input).days > 365 * 7: # Limit to 7 years for FMP calls for performance
    st.sidebar.warning("Note: Selected date range is over 7 years. Data fetching might be slow.")

# Combine custom tickers and selected benchmark tickers for a single fetch operation
tickers_to_fetch_list = sorted(list(set(user_tickers_list + selected_benchmarks_for_overlay)))
tickers_tuple_for_cache = tuple(tickers_to_fetch_list)
price_start_date_str = start_date_input.strftime('%Y-%m-%d')
price_end_date_str = end_date_input.strftime('%Y-%m-%d')

# --- Fetch ALL Price Data ---
all_fetched_prices, successful_all_fetches, problematic_all_fetches = {}, [], []
if tickers_tuple_for_cache: # Only proceed if there are tickers to fetch
    with st.spinner(f"Fetching FMP EOD prices for {len(tickers_to_fetch_list)} symbols... This may take a moment."):
        all_fetched_prices, successful_all_fetches, problematic_all_fetches = fetch_fmp_daily_prices(
            tickers_tuple_for_cache, FMP_API_KEY, price_start_date_str, price_end_date_str
        )

# Display any fetching issues
if problematic_all_fetches:
    st.sidebar.write("---"); st.sidebar.subheader("⚠️ FMP Price Fetching Issues:")
    for ticker, error_msg in problematic_all_fetches:
        st.sidebar.warning(f"**{ticker}:** {error_msg}")

# --- Prepare Data for Custom ETF ---
custom_etf_prices = {t: all_fetched_prices[t] for t in user_tickers_list if t in successful_all_fetches and all_fetched_prices.get(t) is not None and not all_fetched_prices[t].empty}
successful_custom_tickers = [t for t in user_tickers_list if t in custom_etf_prices] # Tickers that are part of user list AND successfully fetched

if not successful_custom_tickers:
    st.error("Failed to fetch prices for ANY of your custom ETF tickers. Cannot build or display custom ETF."); st.stop()

custom_etf_df = pd.DataFrame(custom_etf_prices)
custom_etf_df.dropna(how='all', inplace=True) # Drop days where all custom tickers had no data

if custom_etf_df.empty:
    st.warning(f"No price data available for your custom ETF components within the period: {price_start_date_str} to {price_end_date_str}."); st.stop()

# Final list of custom tickers that have data in the combined DataFrame
valid_custom_tickers_for_pw = [t for t in successful_custom_tickers if t in custom_etf_df.columns and not custom_etf_df[t].isnull().all()]
if not valid_custom_tickers_for_pw:
    st.error("No valid custom tickers with data remaining after processing for the selected period."); st.stop()

# Calculate Price-Weighted Custom ETF
custom_etf_df['Portfolio Sum'] = custom_etf_df[valid_custom_tickers_for_pw].sum(axis=1)
custom_etf_df['My Custom ETF'] = custom_etf_df['Portfolio Sum'] / len(valid_custom_tickers_for_pw)

# --- SECTION 1: Custom ETF Performance (with optional Benchmark Overlay) ---
st.header(f"⚖️ Your Custom Price-Weighted ETF Performance")
st.caption(f"Constituents: {', '.join(valid_custom_tickers_for_pw)}")

chart_data_main_etf = pd.DataFrame()
if 'My Custom ETF' in custom_etf_df.columns and not custom_etf_df['My Custom ETF'].isnull().all():
    chart_data_main_etf['My Custom ETF'] = custom_etf_df['My Custom ETF']
else:
    st.warning("Custom ETF price could not be calculated (e.g., all constituent data was NaN for the period).")

# Add selected benchmarks to this chart
for bench_ticker in selected_benchmarks_for_overlay:
    if bench_ticker in successful_all_fetches and all_fetched_prices.get(bench_ticker) is not None and not all_fetched_prices[bench_ticker].empty:
        # Ensure benchmark data is aligned with custom ETF's index if combining
        benchmark_series = all_fetched_prices[bench_ticker]
        # chart_data_main_etf[f"{bench_ticker} ({BENCHMARK_ETFS[bench_ticker]})"] = benchmark_series # Direct add
        # For cleaner plot if date ranges differ slightly after API fetch for some symbols:
        aligned_benchmark, _ = benchmark_series.align(chart_data_main_etf['My Custom ETF'], join='right', copy=False) # Align to custom ETF's index
        chart_data_main_etf[f"{bench_ticker} ({BENCHMARK_ETFS[bench_ticker]})"] = aligned_benchmark

    else:
        st.sidebar.warning(f"Data for benchmark {bench_ticker} was not successfully fetched or is empty; cannot overlay.")

if not chart_data_main_etf.empty:
    st.line_chart(chart_data_main_etf.dropna(how='all')) # Drop rows if all plotted lines are NaN

    st.subheader("Custom ETF Data Snippet (Price-Weighted)")
    display_cols_custom_etf = valid_custom_tickers_for_pw + ['My Custom ETF']
    st.dataframe(custom_etf_df[display_cols_custom_etf].tail())
else:
    st.warning("Not enough data to display the main ETF performance chart.")

st.markdown("---")

# --- SECTION 2: Normalized Performance of Constituents & Selected Benchmarks ---
st.header("📊 Normalized Performance Comparison (How $100 Would Grow)")
st.caption("Shows the percentage growth of each custom ETF constituent, your custom ETF, and selected benchmarks from the start date.")

data_to_normalize_list = []

# Add Custom ETF Constituents
for ticker in valid_custom_tickers_for_pw: # Use tickers that are valid for the ETF
    if ticker in custom_etf_df.columns and not custom_etf_df[ticker].empty:
        constituent_series = custom_etf_df[ticker].copy()
        constituent_series.name = ticker 
        data_to_normalize_list.append(constituent_series)

# Add Custom ETF itself to normalized chart
if 'My Custom ETF' in chart_data_main_etf.columns and not chart_data_main_etf['My Custom ETF'].empty and not chart_data_main_etf['My Custom ETF'].isnull().all():
    custom_etf_norm_series = chart_data_main_etf['My Custom ETF'].copy() # Use from potentially aligned chart_data_main_etf
    data_to_normalize_list.append(custom_etf_norm_series)

# Add selected Index ETFs (benchmarks) for normalization
for bench_ticker in selected_benchmarks_for_overlay:
    benchmark_col_name = f"{bench_ticker} ({BENCHMARK_ETFS[bench_ticker]})"
    if benchmark_col_name in chart_data_main_etf.columns and not chart_data_main_etf[benchmark_col_name].empty and not chart_data_main_etf[benchmark_col_name].isnull().all():
        idx_series = chart_data_main_etf[benchmark_col_name].copy() # Use from potentially aligned chart_data_main_etf
        # idx_series.name = benchmark_col_name # Name is already set
        data_to_normalize_list.append(idx_series)

if not data_to_normalize_list:
    st.warning("No data available for normalized performance chart.")
else:
    comparison_df_norm = pd.concat(data_to_normalize_list, axis=1)
    comparison_df_norm.dropna(how='all', inplace=True) # Drop rows where all values are NaN

    if comparison_df_norm.empty:
        st.warning("Not enough overlapping data for normalized comparison chart.")
    else:
        normalized_df = pd.DataFrame(index=comparison_df_norm.index)
        for col in comparison_df_norm.columns:
            series_to_norm = comparison_df_norm[col].copy()
            # Find first non-NaN value to use as the base by backfilling then taking first valid index
            # This ensures that even if a series starts with NaNs, we find its true first data point.
            bfilled_series = series_to_norm.bfill()
            if not bfilled_series.empty and not bfilled_series.isnull().all():
                first_valid_value = bfilled_series.iloc[0]
                if pd.notna(first_valid_value) and first_valid_value != 0:
                    normalized_df[col] = (series_to_norm / first_valid_value) * 100
                else:
                    normalized_df[col] = pd.NA 
            else:
                 normalized_df[col] = pd.NA


        st.line_chart(normalized_df.dropna(how='all', axis=1)) # Drop columns that are entirely NA after normalization attempt

st.markdown("---")
st.info("Disclaimer: Educational tool. Data from Financial Modeling Prep. API usage subject to FMP terms and plan limits.")
