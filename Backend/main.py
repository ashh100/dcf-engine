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
    
# --- NEW: THE QUANT-GRADE DCF VALUATION ENDPOINT ---
@app.get("/valuation/{ticker}")
def get_valuation(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        cf = stock.cashflow
        bs = stock.balance_sheet
        inc_stmt = stock.income_stmt 
        fast_info = stock.fast_info
        info = stock.info  # Used carefully for Beta

        if cf.empty or 'Free Cash Flow' not in cf.index:
            raise HTTPException(status_code=404, detail="No Free Cash Flow data found.")

        # --- 1. CORE DATA EXTRACTION ---
        try:
            shares = fast_info['shares']
            current_price = fast_info['lastPrice']
        except KeyError:
            raise HTTPException(status_code=404, detail="Core pricing/shares data missing.")

        total_cash = bs.loc['Cash And Cash Equivalents'].iloc[0] if 'Cash And Cash Equivalents' in bs.index else 0
        total_debt = bs.loc['Total Debt'].iloc[0] if 'Total Debt' in bs.index else 0
        market_cap = shares * current_price

        # --- 2. DYNAMIC WACC CALCULATION (CAPM) ---
        # A. Risk-Free Rate (Live 10-Yr Treasury)
        try:
            tnx_yield = yf.Ticker("^TNX").fast_info['lastPrice']
            risk_free_rate = tnx_yield / 100
        except Exception:
            risk_free_rate = 0.042  # Fallback to 4.2% if Treasury data fails

        # B. Beta (Volatility)
        beta = info.get('beta', 1.0)

        # C. Cost of Equity
        expected_market_return = 0.10
        cost_of_equity = risk_free_rate + (beta * (expected_market_return - risk_free_rate))

        # D. Cost of Debt & Tax Rate
        try:
            interest_expense = inc_stmt.loc['Interest Expense'].iloc[0]
            cost_of_debt = interest_expense / total_debt if total_debt > 0 else 0
        except Exception:
            cost_of_debt = 0.05  # Fallback to 5%

        try:
            tax_provision = inc_stmt.loc['Tax Provision'].iloc[0]
            pretax_income = inc_stmt.loc['Pretax Income'].iloc[0]
            tax_rate = tax_provision / pretax_income if pretax_income > 0 else 0.21
        except Exception:
            tax_rate = 0.21  # Standard corporate rate

        # E. Final WACC Calculation
        total_capital = market_cap + total_debt
        weight_equity = market_cap / total_capital if total_capital > 0 else 1
        weight_debt = total_debt / total_capital if total_capital > 0 else 0

        calculated_wacc = (weight_equity * cost_of_equity) + (weight_debt * cost_of_debt * (1 - tax_rate))
        
        # Guardrail: Cap WACC between 6% and 15% so weird accounting anomalies don't break the model
        wacc = max(0.06, min(calculated_wacc, 0.15))

        # --- 3. PROJECT FCF & TERMINAL VALUE ---
        fcf_series = cf.loc['Free Cash Flow'].dropna().sort_index()
        growth_rates = fcf_series.pct_change().dropna()
        g = max(0.02, min(growth_rates.mean(), 0.15))

        last_fcf = fcf_series.iloc[-1]
        future_fcf = [last_fcf * ((1 + g) ** i) for i in range(1, 6)]

        perpetual_growth = 0.025
        terminal_value = (future_fcf[-1] * (1 + perpetual_growth)) / (wacc - perpetual_growth)

        pv_fcf = sum([f / ((1 + wacc) ** i) for i, f in enumerate(future_fcf, 1)])
        pv_tv = terminal_value / ((1 + wacc) ** 5)
        
        # --- 4. INTRINSIC VALUE ---
        enterprise_value = pv_fcf + pv_tv
        equity_value = enterprise_value + total_cash - total_debt
        intrinsic_value_per_share = equity_value / shares

        return {
            "ticker": ticker.upper(),
            "current_price": round(current_price, 2),
            "intrinsic_value": round(intrinsic_value_per_share, 2),
            "assumptions": {
                "projected_growth_rate": f"{round(g * 100, 2)}%",
                "wacc": f"{round(wacc * 100, 2)}%",  # <-- Now showing the dynamic WACC!
                "perpetual_growth": "2.5%",
                "beta_used": round(beta, 2)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))