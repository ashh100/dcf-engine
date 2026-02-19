// --- 1. THE GET DATA LOGIC (For the Button) ---
async function fetchCashFlow() {
    const ticker = document.getElementById('tickerInput').value;
    const resultDiv = document.getElementById('result');
    const loadingDiv = document.getElementById('loading');

    // Make sure they typed something
    if (!ticker) {
        alert("Please enter a ticker symbol!");
        return;
    }

    // Clear old data and show a loading message
    resultDiv.innerHTML = ""; 
    loadingDiv.style.display = "block"; 

    try {
        // Send the request to your Python Backend
        const response = await fetch(`http://127.0.0.1:8000/fcf/${ticker}`);
        const data = await response.json();

        loadingDiv.style.display = "none"; // Hide loading message

        // Display the results
        if (response.ok) {
            let htmlContent = `<h2>${data.ticker} Free Cash Flow</h2><ul>`;
            
            // Loop through the dictionary we sent from Python
            for (const [date, fcf] of Object.entries(data.free_cash_flow)) {
                // .toLocaleString() adds commas to the massive numbers so they are readable
                htmlContent += `<li><strong>${date}:</strong> ${fcf.toLocaleString()}</li>`;
            }
            
            htmlContent += `</ul>`;
            resultDiv.innerHTML = htmlContent;
        } else {
            // If the user typed a fake ticker
            resultDiv.innerHTML = `<p class="error">Error: ${data.detail}</p>`;
        }
    } catch (error) {
        loadingDiv.style.display = "none";
        resultDiv.innerHTML = `<p class="error">Failed to connect. Is your Python Uvicorn server running?</p>`;
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
        const response = await fetch(`http://127.0.0.1:8000/search/${query}`);
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