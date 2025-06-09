import streamlit as st
import pandas as pd
import requests # For making API calls to FMP
import datetime as dt
import time

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="ETF Builder (FMP)", layout="wide")
st.title("📈 ETF Builder (using Financial Modeling Prep)")
st.caption("Create a custom Price-Weighted ETF using FMP End-of-Day stock prices. Caching is used.")

# --- 2. FMP API Key Handling (using st.secrets) ---
FMP_API_KEY = None
try:
    FMP_API_KEY = st.secrets["FMP_API_KEY"]
except (FileNotFoundError, KeyError):
    st.sidebar.error("`FMP_API_KEY` not found in Streamlit secrets (.streamlit/secrets.toml).")
    # For local development, you could add a temporary fallback input here
    # temp_key = st.sidebar.text_input("TEMPORARY: Enter FMP Key for local dev", type="password", key="temp_fmp_key")
    # if temp_key: FMP_API_KEY = temp_key

if not FMP_API_KEY:
    st.error("CRITICAL: FMP API Key is not configured. Please set it in `.streamlit/secrets.toml` for this app to function.")
    st.stop()

# --- 3. CACHED DATA FETCHING FUNCTION (FMP - Time Series) ---
@st.cache_data(ttl="4h") # Cache EOD prices for 4 hours
def fetch_fmp_daily_prices(tickers_tuple, api_key_param, start_date_str, end_date_str):
    st.sidebar.info(f"♻️ Fetching EOD prices from FMP for: {', '.join(tickers_tuple)} ({start_date_str} to {end_date_str})...")
    
    _all_stock_close_prices = {}
    _successful_tickers = []
    _problematic_items = []
    
    # FMP API base URL for historical daily prices
    base_url = "https://financialmodelingprep.com/api/v3/historical-price-full/"

    for i, ticker in enumerate(tickers_tuple):
        # FMP rate limits depend on your plan. Free tier might be ~250 requests/day.
        # Paid plans have much higher limits. Let's add a small, respectful delay.
        if i > 0:
            st.sidebar.write(f"Pausing ~0.5s for FMP before {ticker}...")
            time.sleep(0.5) 
        
        try:
            st.sidebar.caption(f"Fetching FMP EOD for {ticker}...")
            # Construct the full URL with date range
            url = f"{base_url}{ticker}?from={start_date_str}&to={end_date_str}&apikey={api_key_param}"
            response = requests.get(url, timeout=15) # Added timeout
            response.raise_for_status() # Raises an HTTPError if the HTTP request returned an unsuccessful status code
            
            data = response.json()

            if "historical" in data and data["historical"]:
                # Convert list of dicts to DataFrame
                price_df = pd.DataFrame(data["historical"])
                price_df['date'] = pd.to_datetime(price_df['date'])
                price_df = price_df.set_index('date').sort_index(ascending=True)
                
                if 'close' in price_df.columns:
                    _all_stock_close_prices[ticker] = price_df['close'].astype(float)
                    _successful_tickers.append(ticker)
                    st.sidebar.write(f"✅ FMP: Fetched EOD for {ticker}")
                else:
                    _problematic_items.append((ticker, "FMP EOD: 'close' column not found in historical data."))
            elif "Error Message" in data:
                 _problematic_items.append((ticker, f"FMP API Error: {data['Error Message']}"))
                 st.sidebar.warning(f"FMP API Error for {ticker}: {data['Error Message']}")
            else:
                _problematic_items.append((ticker, f"FMP EOD: No 'historical' data found for {ticker}. Response: {str(data)[:100]}"))
        
        except requests.exceptions.HTTPError as http_err:
            err_msg = f"FMP HTTP Error for {ticker}: {http_err} - Response: {response.text[:200]}"
            _problematic_items.append((ticker, err_msg))
            st.sidebar.warning(err_msg)
        except requests.exceptions.RequestException as req_err: # Catch other requests errors (timeout, connection)
            err_msg = f"FMP Request Error for {ticker}: {req_err}"
            _problematic_items.append((ticker, err_msg))
            st.sidebar.warning(err_msg)
        except Exception as e:
            err_msg = f"FMP General Error for {ticker}: {str(e)[:200]}"
            _problematic_items.append((ticker, err_msg))
            st.sidebar.warning(err_msg)
            
    return _all_stock_close_prices, _successful_tickers, _problematic_items

# --- 4. SIDEBAR FOR USER INPUTS ---
st.sidebar.header("🛠️ ETF Configuration (FMP)")

raw_tickers_input = st.sidebar.text_input(
    "Stock Tickers (comma-separated)",
    "AAPL,MSFT,GOOG,NVDA" # FMP generally has good US coverage
)

# FMP takes date ranges directly, so output_size selector is not needed like for Alpha Vantage 'compact'/'full'
default_start_date = dt.date.today() - dt.timedelta(days=365 * 5) # Default to 5 years
default_end_date = dt.date.today() - dt.timedelta(days=1) # Yesterday

start_date_input = st.sidebar.date_input("Start Date", default_start_date)
end_date_input = st.sidebar.date_input("End Date", default_end_date)

st.sidebar.write("---")
if st.sidebar.button("Clear FMP Price Data Cache & Rerun"):
    st.cache_data.clear()
    st.sidebar.success("FMP Price data cache cleared! Rerunning...")
    st.rerun()

# --- 5. MAIN APP LOGIC ---
if not raw_tickers_input: st.warning("Please enter stock tickers."); st.stop()
cleaned_tickers = sorted(list(set(t.strip().upper() for t in raw_tickers_input.split(',') if t.strip())))
if not cleaned_tickers: st.warning("No valid stock tickers processed."); st.stop()

if start_date_input >= end_date_input: 
    st.error("Start date must be before end date.")
    st.stop()
if (end_date_input - start_date_input).days > 365 * 10: # Arbitrary limit to prevent extremely long FMP calls
    st.warning("Date range too long (max ~10 years recommended for performance). Please shorten.")
    st.stop()


tickers_tuple_for_cache = tuple(cleaned_tickers)
start_date_str = start_date_input.strftime('%Y-%m-%d')
end_date_str = end_date_input.strftime('%Y-%m-%d')


# --- Fetch Price Data ---
st.write("---")
with st.spinner(f"Fetching FMP EOD prices for {', '.join(cleaned_tickers)}..."):
    all_stock_close_prices, successful_price_tickers, problematic_price_items = fetch_fmp_daily_prices(
        tickers_tuple_for_cache, FMP_API_KEY, start_date_str, end_date_str
    )

# --- Display Price Fetching Issues ---
if problematic_price_items:
    st.sidebar.write("---")
    st.sidebar.subheader("⚠️ FMP EOD Price Fetching Issues:")
    for ticker, error_msg in problematic_price_items:
        st.sidebar.warning(f"**{ticker}:** {error_msg}")

if not successful_price_tickers:
    st.error("FMP: Failed to fetch EOD prices for ANY tickers. Cannot build ETF."); st.stop()
if not all_stock_close_prices:
    st.error("FMP: No EOD stock price data was returned. Cannot build ETF."); st.stop()

# --- Create Price DataFrame ---
prices_for_df = {tick: data for tick, data in all_stock_close_prices.items() if tick in successful_price_tickers and data is not None and not data.empty}
if not prices_for_df: st.warning("FMP: No price data available for ETF construction."); st.stop()

etf_df = pd.DataFrame(prices_for_df)
# FMP data is already indexed by date correctly if parsed as above
# etf_df.index = pd.to_datetime(etf_df.index) # Already done in fetch if data["historical"] was processed
etf_df.dropna(how='all', inplace=True)

if etf_df.empty: 
    st.warning(f"FMP: No price data available for the selected period after processing: {start_date_str} to {end_date_str}.")
    st.stop()

# --- ETF Calculation (Price-Weighted) ---
st.subheader(f"📈 Price-Weighted ETF Performance (FMP Data)")
valid_tickers_for_etf = [tick for tick in successful_price_tickers if tick in etf_df.columns and not etf_df[tick].isnull().all()]

if not valid_tickers_for_etf:
    st.error("FMP: No valid tickers with data remaining for ETF calculation."); st.stop()

st.info(f"Building Price-Weighted ETF with FMP data for: {', '.join(valid_tickers_for_etf)}")

etf_df['Portfolio Sum'] = etf_df[valid_tickers_for_etf].sum(axis=1)
etf_df['ETF Price'] = etf_df['Portfolio Sum'] / len(valid_tickers_for_etf)

# --- Display ETF Chart and Data ---
if 'ETF Price' in etf_df.columns and not etf_df['ETF Price'].empty and not etf_df['ETF Price'].isnull().all():
    st.line_chart(etf_df['ETF Price'])

    st.subheader("📊 Individual Stock Prices (Normalized - FMP Data)")
    df_for_normalization = etf_df[valid_tickers_for_etf].copy().dropna(how='all')
    if not df_for_normalization.empty:
        normalized_values = pd.DataFrame(index=df_for_normalization.index)
        if not df_for_normalization.empty: # Check again after potential dropna
            first_valid_overall_idx = df_for_normalization.bfill().index[0] 
            for col in df_for_normalization.columns:
                col_bfilled_from_start = df_for_normalization[col].bfill()
                if not col_bfilled_from_start.loc[first_valid_overall_idx:].empty and not pd.isna(col_bfilled_from_start.loc[first_valid_overall_idx:].iloc[0]):
                    first_val = col_bfilled_from_start.loc[first_valid_overall_idx:].iloc[0]
                    normalized_values[col] = (df_for_normalization[col] / first_val) * 100
                else:
                    normalized_values[col] = pd.NA
            
            if not normalized_values.empty:
                 st.line_chart(normalized_values.dropna(axis=1, how='all'))
            else:
                 st.caption("FMP: Could not normalize individual stock prices.")
        else:
            st.caption("FMP: Not enough data for normalized individual stock prices.")

    st.subheader("📋 ETF Data Snippet (Last 5 entries - FMP Data)")
    display_cols = valid_tickers_for_etf + ['ETF Price']
    st.dataframe(etf_df[display_cols].tail())
else:
    st.warning("FMP: ETF Price could not be calculated or is empty.")

st.write("---")
st.info("Disclaimer: Educational tool. Data from Financial Modeling Prep (API usage subject to FMP terms and plan limits).")