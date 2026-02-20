// --- 1. THE GET DATA LOGIC (For the Button) ---
// --- 1. THE UPGRADED GET DATA LOGIC ---
async function fetchCashFlow() {
    const ticker = document.getElementById('tickerInput').value;
    const resultDiv = document.getElementById('result');
    const loadingDiv = document.getElementById('loading');

    if (!ticker) {
        alert("Please enter a ticker symbol!");
        return;
    }

    resultDiv.innerHTML = ""; 
    loadingDiv.style.display = "block"; 

    try {
        // Fetch BOTH the historical data and the new valuation math at the same time
        const [fcfResponse, valResponse] = await Promise.all([
            fetch(`https://dcf-backend-u7s9.onrender.com/fcf/${ticker}`),
            fetch(`https://dcf-backend-u7s9.onrender.com/valuation/${ticker}`)
        ]);

        const fcfData = await fcfResponse.json();
        const valData = await valResponse.json();

        loadingDiv.style.display = "none"; 

        if (fcfResponse.ok && valResponse.ok) {
            // Determine if the stock is a good deal (Green) or too expensive (Red)
            const isUndervalued = valData.intrinsic_value > valData.current_price;
            const color = isUndervalued ? "#4caf50" : "#ff4d4d";
            const verdict = isUndervalued ? "UNDERVALUED (BUY)" : "OVERVALUED (SELL)";

            // Build the Dashboard HTML
            let htmlContent = `
                <div style="background-color: #2c2c2c; padding: 20px; border-radius: 8px; margin-bottom: 20px; border: 2px solid ${color};">
                    <h2>${valData.ticker} Valuation Model</h2>
                    <h3 style="margin: 5px 0;">Current Market Price: $${valData.current_price}</h3>
                    <h3 style="margin: 5px 0; color: ${color};">Intrinsic Value: $${valData.intrinsic_value}</h3>
                    <h4 style="color: ${color}; margin-top: 15px;">Verdict: ${verdict}</h4>
                    <hr style="border-color: #444; margin: 15px 0;">
                    <p style="font-size: 14px; color: #aaa;">
                        Assumptions: ${valData.assumptions.projected_growth_rate} Growth | ${valData.assumptions.wacc} WACC | ${valData.assumptions.perpetual_growth} Terminal Rate
                    </p>
                </div>
                <h3>Historical Free Cash Flow</h3>
                <ul>
            `;
            
            // Add the historical FCF list
            for (const [date, fcf] of Object.entries(fcfData.free_cash_flow)) {
                htmlContent += `<li><strong>${date}:</strong> ${fcf.toLocaleString()}</li>`;
            }
            
            htmlContent += `</ul>`;
            resultDiv.innerHTML = htmlContent;
        } else {
            resultDiv.innerHTML = `<p class="error">Error fetching data. Ensure the ticker is valid.</p>`;
        }
    } catch (error) {
        loadingDiv.style.display = "none";
        resultDiv.innerHTML = `<p class="error">Failed to connect to Python backend.</p>`;
    }
}

// --- 2. THE AUTO-COMPLETE LOGIC (For the Dropdown) ---
async function searchCompany() {
    const query = document.getElementById('tickerInput').value;
    const suggestionsList = document.getElementById('suggestions');

    // Only search if they typed at least 2 letters
    if (query.length < 2) {
        suggestionsList.innerHTML = '';
        suggestionsList.style.display = 'none';
        return;
    }

    try {
        const response = await fetch(`http://https://dcf-backend-u7s9.onrender.com/search/${query}`);
        const data = await response.json();
        
        suggestionsList.innerHTML = ''; // Clear old suggestions
        
        if (data.results && data.results.length > 0) {
            data.results.forEach(item => {
                const li = document.createElement('li');
                li.textContent = `${item.symbol} - ${item.name}`;
                
                // When they click a dropdown item, fill the search bar with the exact ticker
                li.onclick = () => {
                    document.getElementById('tickerInput').value = item.symbol;
                    suggestionsList.innerHTML = '';
                    suggestionsList.style.display = 'none';
                };
                suggestionsList.appendChild(li);
            });
            suggestionsList.style.display = 'block'; // Show the dropdown
        } else {
            suggestionsList.style.display = 'none';
        }
    } catch (error) {
        console.error("Search failed", error);
    }
}