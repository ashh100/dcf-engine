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