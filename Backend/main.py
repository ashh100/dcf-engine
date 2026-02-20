from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import requests  # <-- Added for the search dropdown

app = FastAPI()

# --- The CORS Bridge ---
# This allows your JavaScript frontend to talk to this Python backend without being blocked by the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows any frontend to connect. We will restrict this to your GitHub Pages URL later.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- NEW: AUTO-COMPLETE SEARCH ENDPOINT ---
@app.get("/search/{query}")
def search_ticker(query: str):
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        valid_types = ["EQUITY", "ETF", "MUTUALFUND"]
        results = [
            {"symbol": q["symbol"], "name": q.get("shortname", "Unknown")} 
            for q in data.get("quotes", []) 
            if q.get("quoteType") in valid_types
        ]
        return {"results": results[:6]}
    except Exception:
        return {"results": []}

# --- EXACT ORIGINAL FCF ENDPOINT (Untouched) ---
@app.get("/fcf/{ticker}")
def get_free_cash_flow(ticker: str):
    try:
        # 1. Fetch the stock data from Yahoo Finance
        stock = yf.Ticker(ticker)
        cf = stock.cashflow
        
        if cf.empty:
            raise HTTPException(status_code=404, detail="No cash flow data found for this ticker.")
        
        # 2. Extract the 'Free Cash Flow' row directly
        # yfinance conveniently calculates this for us (Operating Cash Flow - CapEx)
        fcf_data = cf.loc['Free Cash Flow'].dropna().to_dict()
        
        # 3. Format the dates cleanly for our JSON response
        formatted_data = {str(date.date()): value for date, value in fcf_data.items()}
        
        return {
            "ticker": ticker.upper(),
            "free_cash_flow": formatted_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# --- NEW: THE DCF VALUATION ENDPOINT ---
@app.get("/valuation/{ticker}")
def get_valuation(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        cf = stock.cashflow
        bs = stock.balance_sheet  # <-- NEW: Get cash/debt securely here
        
        # <-- NEW: fast_info bypasses Yahoo's cloud blockers!
        fast_info = stock.fast_info 

        if cf.empty or 'Free Cash Flow' not in cf.index:
            raise HTTPException(status_code=404, detail="No Free Cash Flow data found.")

        # 1. Get Historical FCF and sort from oldest to newest
        fcf_series = cf.loc['Free Cash Flow'].dropna().sort_index()
        if len(fcf_series) < 2:
            raise HTTPException(status_code=400, detail="Not enough history to project growth.")

        # 2. Calculate Average Growth Rate (Cap it between 2% and 15% for realistic models)
        growth_rates = fcf_series.pct_change().dropna()
        avg_growth = growth_rates.mean()
        g = max(0.02, min(avg_growth, 0.15))

        # 3. Project next 5 years of FCF
        last_fcf = fcf_series.iloc[-1]
        future_fcf = []
        for i in range(1, 6):
            next_fcf = last_fcf * ((1 + g) ** i)
            future_fcf.append(next_fcf)

        # 4. Terminal Value
        wacc = 0.10  # 10% discount rate
        perpetual_growth = 0.025  # 2.5% long-term growth
        terminal_value = (future_fcf[-1] * (1 + perpetual_growth)) / (wacc - perpetual_growth)

        # 5. Discount to Present Value
        pv_fcf = sum([cf / ((1 + wacc) ** i) for i, cf in enumerate(future_fcf, 1)])
        pv_tv = terminal_value / ((1 + wacc) ** 5)
        enterprise_value = pv_fcf + pv_tv

        # 6. Calculate Per Share Value using fast_info & balance_sheet
        try:
            shares = fast_info['shares']
        except KeyError:
            raise HTTPException(status_code=404, detail="Shares outstanding data missing.")

        # Safely pull cash and debt from the balance sheet
        total_cash = bs.loc['Cash And Cash Equivalents'].iloc[0] if 'Cash And Cash Equivalents' in bs.index else 0
        total_debt = bs.loc['Total Debt'].iloc[0] if 'Total Debt' in bs.index else 0
        
        equity_value = enterprise_value + total_cash - total_debt
        intrinsic_value_per_share = equity_value / shares
        
        # Safely pull the last live price
        current_price = fast_info['lastPrice']

        return {
            "ticker": ticker.upper(),
            "current_price": round(current_price, 2),
            "intrinsic_value": round(intrinsic_value_per_share, 2),
            "assumptions": {
                "projected_growth_rate": f"{round(g * 100, 2)}%",
                "wacc": "10.0%",
                "perpetual_growth": "2.5%"
            }
        }

    except HTTPException:
        raise  # <-- NEW: Allows our specific 400/404 errors to actually show up!
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))