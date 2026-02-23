from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import requests
import math
import traceback

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/fcf/{ticker}")
def get_free_cash_flow(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        cf = stock.cashflow
        if cf.empty or 'Free Cash Flow' not in cf.index:
            raise HTTPException(status_code=404, detail="No cash flow data found.")
        
        fcf_data = cf.loc['Free Cash Flow'].dropna().to_dict()
        formatted_data = {str(date.date()): value for date, value in fcf_data.items()}
        return {"ticker": ticker.upper(), "free_cash_flow": formatted_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# --- BULLETPROOF QUANT-GRADE DCF ENDPOINT ---
@app.get("/valuation/{ticker}")
def get_valuation(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        cf = stock.cashflow
        bs = stock.balance_sheet
        inc_stmt = stock.income_stmt 
        info = stock.info  

        if cf.empty or 'Free Cash Flow' not in cf.index:
            raise HTTPException(status_code=404, detail="No Free Cash Flow data found.")

        # --- 1. SAFE DATA EXTRACTION ---
        shares = info.get('sharesOutstanding', info.get('impliedSharesOutstanding'))
        current_price = info.get('currentPrice', info.get('previousClose'))
        
        # Fallback if the standard 'info' dictionary is missing pricing
        if not shares or not current_price:
            try:
                shares = stock.fast_info.shares
                current_price = stock.fast_info.last_price
            except Exception:
                raise HTTPException(status_code=404, detail="Core pricing/shares data missing.")

        # Helper function to safely extract dataframe values and catch NaNs
        def safe_extract(df, row_name):
            if df is not None and not df.empty and row_name in df.index:
                val = df.loc[row_name].iloc[0]
                return val if not math.isnan(val) else 0
            return 0

        total_cash = safe_extract(bs, 'Cash And Cash Equivalents')
        total_debt = safe_extract(bs, 'Total Debt')
        market_cap = shares * current_price

        # --- 2. DYNAMIC WACC CALCULATION (CAPM) ---
        try:
            tnx = yf.Ticker("^TNX")
            risk_free_rate = tnx.fast_info.last_price / 100
        except Exception:
            risk_free_rate = 0.042  # 4.2% Fallback

        beta = info.get('beta', 1.0)
        if beta is None or math.isnan(beta): 
            beta = 1.0 

        expected_market_return = 0.10
        cost_of_equity = risk_free_rate + (beta * (expected_market_return - risk_free_rate))

        interest_expense = safe_extract(inc_stmt, 'Interest Expense')
        cost_of_debt = interest_expense / total_debt if total_debt > 0 else 0.05

        tax_provision = safe_extract(inc_stmt, 'Tax Provision')
        pretax_income = safe_extract(inc_stmt, 'Pretax Income')
        tax_rate = tax_provision / pretax_income if pretax_income > 0 else 0.21

        total_capital = market_cap + total_debt
        weight_equity = market_cap / total_capital if total_capital > 0 else 1
        weight_debt = total_debt / total_capital if total_capital > 0 else 0

        calculated_wacc = (weight_equity * cost_of_equity) + (weight_debt * cost_of_debt * (1 - tax_rate))
        wacc = max(0.06, min(calculated_wacc, 0.15))

        # --- 3. PROJECT FCF & TERMINAL VALUE ---
        fcf_series = cf.loc['Free Cash Flow'].dropna().sort_index()
        growth_rates = fcf_series.pct_change().dropna()
        
        avg_growth = growth_rates.mean()
        if math.isnan(avg_growth):
            avg_growth = 0.05  # Fallback to 5% if growth math fails
            
        g = max(0.02, min(avg_growth, 0.15))

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
                "wacc": f"{round(wacc * 100, 2)}%", 
                "perpetual_growth": "2.5%",
                "beta_used": round(beta, 2)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        # Prints the EXACT line of failure to your Render logs
        print(f"CRITICAL ERROR for {ticker}:")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))