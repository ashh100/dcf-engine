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
        if cf is None or cf.empty or 'Free Cash Flow' not in cf.index:
            raise HTTPException(status_code=404, detail="No cash flow data found.")
        
        fcf_data = cf.loc['Free Cash Flow'].dropna().to_dict()
        formatted_data = {str(date.date()): value for date, value in fcf_data.items()}
        return {"ticker": ticker.upper(), "free_cash_flow": formatted_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

# --- INDESTRUCTIBLE QUANT-GRADE DCF ENDPOINT ---
@app.get("/valuation/{ticker}")
def get_valuation(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        
        # 1. SAFELY GET CASH FLOW
        cf = stock.cashflow
        if cf is None or cf.empty or 'Free Cash Flow' not in cf.index:
            raise HTTPException(status_code=404, detail="No Free Cash Flow data found.")
        
        fcf_series = cf.loc['Free Cash Flow'].dropna().sort_index()
        if fcf_series.empty:
            raise HTTPException(status_code=404, detail="Free Cash Flow data is empty.")

        # 2. SAFELY GET PRICING & SHARES
        info = stock.info or {}
        try:
            current_price = float(info.get('currentPrice', info.get('previousClose', stock.fast_info.get('lastPrice', 100))))
            shares = float(info.get('sharesOutstanding', info.get('impliedSharesOutstanding', stock.fast_info.get('shares', 1000000))))
        except Exception:
            raise HTTPException(status_code=404, detail="Missing core pricing data.")

        market_cap = current_price * shares

        # 3. SAFE BALANCE SHEET & INCOME STATEMENT EXTRACTION
        # (Yahoo frequently blocks these on cloud servers, so we use safe defaults if they fail)
        total_cash, total_debt = 0.0, 0.0
        cost_of_debt, tax_rate = 0.05, 0.21

        try:
            bs = stock.balance_sheet
            if bs is not None and not bs.empty:
                if 'Cash And Cash Equivalents' in bs.index:
                    val = bs.loc['Cash And Cash Equivalents'].iloc[0]
                    total_cash = float(val) if val and not math.isnan(val) else 0.0
                if 'Total Debt' in bs.index:
                    val = bs.loc['Total Debt'].iloc[0]
                    total_debt = float(val) if val and not math.isnan(val) else 0.0
                    
            inc_stmt = stock.income_stmt
            if inc_stmt is not None and not inc_stmt.empty:
                if 'Interest Expense' in inc_stmt.index and total_debt > 0:
                    ie = inc_stmt.loc['Interest Expense'].iloc[0]
                    if ie and not math.isnan(ie):
                        cost_of_debt = float(ie) / total_debt
                if 'Tax Provision' in inc_stmt.index and 'Pretax Income' in inc_stmt.index:
                    tp = inc_stmt.loc['Tax Provision'].iloc[0]
                    pi = inc_stmt.loc['Pretax Income'].iloc[0]
                    if tp and pi and pi > 0 and not math.isnan(tp) and not math.isnan(pi):
                        tax_rate = float(tp) / float(pi)
        except Exception:
            pass # Silently proceed with default 5% debt cost and 21% tax rate

        # 4. CAPM WACC CALCULATION
        beta = info.get('beta', 1.0)
        if beta is None or math.isnan(beta):
            beta = 1.0
            
        risk_free_rate = 0.042 # Hardcoded to 4.2% to prevent Treasury fetch crashes
        expected_market_return = 0.10
        cost_of_equity = risk_free_rate + (beta * (expected_market_return - risk_free_rate))

        total_capital = market_cap + total_debt
        weight_equity = market_cap / total_capital if total_capital > 0 else 1.0
        weight_debt = total_debt / total_capital if total_capital > 0 else 0.0

        wacc = (weight_equity * cost_of_equity) + (weight_debt * cost_of_debt * (1 - tax_rate))
        wacc = max(0.06, min(wacc, 0.15)) # Guardrail: Cap WACC between 6% and 15%

        # 5. PROJECT FCF & TERMINAL VALUE
        growth_rates = fcf_series.pct_change().dropna()
        avg_growth = growth_rates.mean() if not growth_rates.empty else 0.05
        if math.isnan(avg_growth):
            avg_growth = 0.05
            
        g = max(0.02, min(avg_growth, 0.15)) # Guardrail: Cap growth between 2% and 15%

        last_fcf = float(fcf_series.iloc[-1])
        future_fcf = [last_fcf * ((1 + g) ** i) for i in range(1, 6)]
        
        perpetual_growth = 0.025
        
        # Prevent division by zero if WACC equals perpetual growth
        if wacc <= perpetual_growth:
            wacc = perpetual_growth + 0.01 
            
        terminal_value = (future_fcf[-1] * (1 + perpetual_growth)) / (wacc - perpetual_growth)

        pv_fcf = sum([f / ((1 + wacc) ** i) for i, f in enumerate(future_fcf, 1)])
        pv_tv = terminal_value / ((1 + wacc) ** 5)

        # 6. FINAL INTRINSIC VALUE
        enterprise_value = pv_fcf + pv_tv
        equity_value = enterprise_value + total_cash - total_debt
        intrinsic_value = equity_value / shares if shares > 0 else 0

        return {
            "ticker": ticker.upper(),
            "current_price": round(current_price, 2),
            "intrinsic_value": round(intrinsic_value, 2),
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
        print(f"CRITICAL ERROR for {ticker}:")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Calculation failed. Check Render logs.")