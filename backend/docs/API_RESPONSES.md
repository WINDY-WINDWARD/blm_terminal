BLM Analytics API Documentation
Base URL: http://127.0.0.1:4455
Generated: /mnt/drive3/500GB/p1/Projects/blm_terminal/backend/docs/api_responses.py

============================================================
  GET /health
============================================================
Status: 200
{
  "status": "ok"
}

============================================================
  GET /api/stockuniverse
============================================================
Status: 200
Response: List of 2269 items
Sample item (first):
{
  "symbol": "20MICRONS",
  "companyName": "20 Microns Limited",
  "segment": "EQUITY",
  "industry": "Industrial Minerals",
  "sectorPE": 9.13,
  "symbolPE": 9.19,
  "industryInfo": {
    "macro": "Commodities",
    "sector": "Metals & Mining",
    "industry": "Minerals & Mining",
    "basicIndustry": "Industrial Minerals"
  },
  "lastUpdateTime": "2026-03-05T16:00:00",
  "screenerTradesId": null
}

============================================================
  GET /api/stockuniverse/{symbol}
============================================================
Status: 200
{
  "symbol": "RELIANCE",
  "companyName": "Reliance Industries Limited",
  "segment": "EQUITY",
  "industry": "Refineries & Marketing",
  "sectorPE": 18.68,
  "symbolPE": 18.68,
  "industryInfo": {
    "macro": "Energy",
    "sector": "Oil Gas & Consumable Fuels",
    "industry": "Petroleum Products",
    "basicIndustry": "Refineries & Marketing"
  },
  "lastUpdateTime": "2026-03-05T16:00:00",
  "screenerTradesId": "2726"
}

============================================================
  GET /api/stockuniverse/search/{prefix}
============================================================
Status: 200
Response: List of 11 items
Sample item (first):
{
  "symbol": "RCOM",
  "companyName": "Reliance Communications Limited",
  "segment": "EQUITY",
  "industry": "Telecom - Cellular & Fixed line services",
  "sectorPE": null,
  "symbolPE": null,
  "industryInfo": {
    "macro": "Telecommunication",
    "sector": "Telecommunication",
    "industry": "Telecom - Services",
    "basicIndustry": "Telecom - Cellular & Fixed line services"
  },
  "lastUpdateTime": "2026-03-05T16:00:00",
  "screenerTradesId": null
}

============================================================
  GET /api/corporatefilings/{symbol}
============================================================
Status: 200
Response: CSV text (4145 chars)

Full CSV content (first 5000 chars):
```
"QUARTER ENDED"|"31-DEC-2024"|"30-SEP-2024"|"30-JUN-2024"|"31-MAR-2024"|"31-DEC-2023"
"PARTICULARS"|"UNAUDITED"|"UNAUDITED"|"UNAUDITED"|"AUDITED"|"UNAUDITED"
"Part 1"|""|""|""|""|""
"Revenue from operations"|""|""|""|""|""
"Revenue from operations"|"12826000"|"13405400"|"13433100"|"15101400"|"13057900"
"Other income"|"321400"|"380100"|"350200"|"349700"|"296900"
"Total income"|"13147400"|"13785500"|"13783300"|"15451100"|"13354800"
"Expenses"|""|""|""|""|""
"(a) Cost of materials consumed"|"9156100"|"9683600"|"9967900"|"9625900"|"9402100"
"(b) Purchases of stock-in-trade"|"390400"|"338300"|"396700"|"334700"|"378900"
"(c) Changes in inventories of finished goods, work-in-progress and stock-in-trade"|"237100"|"266200"|"296300"|"361300"|"298200"
"(d) Employee benefits expense"|"218100"|"207700"|"215600"|"194600"|"186200"
"(e) Finance costs"|"237100"|"266200"|"296300"|"361300"|"298200"
"(f) Depreciation and amortisation expense"|"445900"|"435000"|"470800"|"485600"|"456700"
"(g) Other expenses"|"1948600"|"1905600"|"1909000"|"2085500"|"1662900"
"Total Expenses"|"11987700"|"12764100"|"12768700"|"13946000"|"12057000"
"Profit / (Loss) before exceptional items and tax"|"-"|"-"|"-"|"-"|"-"
"Exceptional items"|"0"|"0"|"0"|"0"|"0"
"Profit / (Loss) before tax"|"1159700"|"1021400"|"1014600"|"1505100"|"1297800"
"Tax Expenses"|""|""|""|""|""
"Current Tax"|"248300"|"211300"|"245700"|"321200"|"248700"
"Deferred Tax"|"39300"|"38800"|"7800"|"55600"|"56700"
"Total Tax expense"|"287600"|"250100"|"253500"|"376800"|"305400"
"Net movement in regulatory deferral account balances related to profit or loss and the related deferred tax movement"|"-"|"-"|"-"|"-"|"-"
"Profit (Loss) for the period from continuing operations"|"872100"|"771300"|"761100"|"1128300"|"992400"
"Profit / (loss) from discontinued operations"|"0"|"0"|"0"|"0"|"0"
"Tax expense of discontinued operations"|"0"|"0"|"0"|"0"|"0"
"Profit / (loss) from Discontinued operations (after tax)"|"0"|"0"|"0"|"0"|"0"
"Profit / (loss) for the period"|"-"|"-"|"-"|"-"|"-"
"Share of profit / (loss) of associates"|"0"|"0"|"0"|"0"|"0"
"Consolidated Net Profit / Loss for the period"|"872100"|"771300"|"761100"|"1128300"|"992400"
"Other comprehensive income"|"-"|"-"|"-"|"-"|"-"
"Total comprehensive income"|"-"|"-"|"-"|"-"|"-"
"Total profit or loss, attributable to"|""|""|""|""|""
"Profit or loss, attributable to owners of parent"|"-"|"-"|"-"|"-"|"-"
"Total profit or loss, attributable to non-controlling interests"|"-"|"-"|"-"|"-"|"-"
"Total Comprehensive income for the period attributable to"|""|""|""|""|""
"Comprehensive income for the period attributable to owners of parent"|"-"|"-"|"-"|"-"|"-"
"Total comprehensive income for the period attributable to owners of parent non-controlling interests"|"-"|"-"|"-"|"-"|"-"
"Details of equity share capital"|""|""|""|""|""
"Paid-up equity share capital"|"1353200"|"676600"|"676600"|"676600"|"676600"
"Face Value(in Rs.)"|"10"|"10"|"10"|"10"|"10"
"Details of debt securities"|""|""|""|""|""
"Paid-up debt capital"|"-"|"-"|"-"|"-"|"-"
"Face value of debt securities (in Rs.)"|"-"|"-"|"-"|"-"|"-"
"Reserve excluding Revaluation Reserves as per balance sheet of previous accounting year"|"-"|"-"|"-"|"-"|"-"
"Debenture redemption reserve"|"-"|"-"|"-"|"-"|"-"
"Earnings per share"|""|""|""|""|""
"Earnings per equity share for continuing operations"|""|""|""|""|""
"Basic EPS for continuing operations"|"-"|"-"|"-"|"-"|"-"
"Diluted EPS for continuing operations"|"-"|"-"|"-"|"-"|"-"
"Earnings per equity share for discontinued operations"|""|""|""|""|""
"Basic EPS for continued and discontinued operations"|"-"|"-"|"-"|"-"|"-"
"Diluted EPS for discontinued operations"|"-"|"-"|"-"|"-"|"-"
"Earnings per equity share"|""|""|""|""|""
"Basic EPS for continued and discontinued operations"|"6.44"|"11.4"|"11.25"|"16.68"|"14.67"
"Diluted EPS for continued and discontinued operations"|"6.44"|"11.4"|"11.25"|"16.68"|"14.67"
"Debt equity ratio (in %)"|"-"|"-"|"-"|"-"|"-"
"Debt service coverage ratio (in %)"|"-"|"-"|"-"|"-"|"-"
"Interest service coverage ratio (in %)"|"-"|"-"|"-"|"-"|"-"

```

============================================================
  GET /api/market/top-gainers
============================================================
Status: 200
Response: List of 5 items
Sample item (first):
{
  "symbol": "DMART",
  "identifier": "",
  "series": "EQ",
  "open": "3866.9",
  "dayHigh": "3982",
  "dayLow": "3814.5",
  "lastPrice": "3967.1",
  "previousClose": "3875.8",
  "change": 91.3,
  "pChange": 2.36,
  "totalTradedVolume": 933615,
  "totalTradedValue": 3647568451.95,
  "yearHigh": "4949.5",
  "yearLow": "3475",
  "nearWKH": 19.84846954237802,
  "nearWKL": -14.161151079136689,
  "perChange365d": 10.37,
  "perChange30d": 1.96,
  "date365dAgo": "07-Mar-2025",
  "date30dAgo": "06-Feb-2026",
  "chartTodayPath": "https://nsearchives.nseindia.com/today/DMARTEQN.svg",
  "chart30dPath": "https://nsearchives.nseindia.com/30d/DMART-EQ.svg",
  "chart365dPath": "https://nsearchives.nseindia.com/365d/DMART-EQ.svg",
  "meta": {
    "symbol": "DMART",
    "companyName": "Avenue Supermarts Limited",
    "industry": "Diversified Retail",
    "activeSeries": [
      "EQ",
      "T0"
    ],
    "debtSeries": [],
    "isFNOSec": true,
    "isCASec": false,
    "isSLBSec": true,
    "isDebtSec": false,
    "isSuspended": false,
    "tempSuspendedSeries": [],
    "isETFSec": false,
    "isDelisted": false,
    "isin": "INE192R01011",
    "slb_isin": "INE192R01011",
    "listingDate": "2017-03-21",
    "isMunicipalBond": false,
    "isHybridSymbol": false,
    "segment": "EQUITY",
    "quotepreopenstatus": {
      "equityTime": "09-Mar-2026 16:00:00",
      "preOpenTime": "09-Mar-2026 09:07:13",
      "QuotePreOpenFlag": false
    }
  }
}

============================================================
  GET /api/market/top-losers
============================================================
Status: 200
Response: List of 5 items
Sample item (first):
{
  "symbol": "PGEL",
  "identifier": "",
  "series": "EQ",
  "open": "599",
  "dayHigh": "599",
  "dayLow": "517.5",
  "lastPrice": "519.6",
  "previousClose": "609.25",
  "change": -89.65,
  "pChange": -14.71,
  "totalTradedVolume": 11304952,
  "totalTradedValue": 6110552655.04,
  "yearHigh": "1008",
  "yearLow": "465",
  "nearWKH": 48.45238095238095,
  "nearWKL": -11.741935483870972,
  "perChange365d": -40.44,
  "perChange30d": -10.69,
  "date365dAgo": "07-Mar-2025",
  "date30dAgo": "06-Feb-2026",
  "chartTodayPath": "https://nsearchives.nseindia.com/today/PGELEQN.svg",
  "chart30dPath": "https://nsearchives.nseindia.com/30d/PGEL-EQ.svg",
  "chart365dPath": "https://nsearchives.nseindia.com/365d/PGEL-EQ.svg",
  "meta": {
    "symbol": "PGEL",
    "companyName": "PG Electroplast Limited",
    "industry": "Consumer Electronics",
    "activeSeries": [
      "EQ",
      "T0"
    ],
    "debtSeries": [],
    "isFNOSec": true,
    "isCASec": false,
    "isSLBSec": true,
    "isDebtSec": false,
    "isSuspended": false,
    "tempSuspendedSeries": [],
    "isETFSec": false,
    "isDelisted": false,
    "isin": "INE457L01029",
    "slb_isin": "INE457L01029",
    "listingDate": "2011-09-26",
    "isMunicipalBond": false,
    "isHybridSymbol": false,
    "segment": "EQUITY",
    "quotepreopenstatus": {
      "equityTime": "09-Mar-2026 16:00:00",
      "preOpenTime": "09-Mar-2026 09:07:13",
      "QuotePreOpenFlag": false
    }
  }
}

============================================================
  GET /api/market/bulk-deals/{symbol}
============================================================
Status: 200
Response: List of 0 items

============================================================
  GET /api/market/block-deals/{symbol}
============================================================
Status: 200
Response: List of 0 items

============================================================
  GET /api/market/high-short-interest
============================================================
Status: 200
Response: List of 68 items
Sample item (first):
{
  "date": "06-Mar-2026",
  "symbol": "ADANIENSOL",
  "name": "ADANI ENERGY SOLUTION LTD",
  "clientName": null,
  "buySell": null,
  "qty": "5",
  "watp": null,
  "remarks": null
}

============================================================
  GET /api/market/change-ranges/{symbol}
============================================================
Status: 200
{
  "oneDayPercent": -9.96,
  "oneWeekPercent": 4.46,
  "oneMonthPercent": -2.94,
  "threeMonthPercent": -7.24,
  "sixMonthPercent": 3.08,
  "oneYearPercent": 13.51,
  "twoYearPercent": -4.08,
  "threeYearPercent": 20.26,
  "fiveYearPercent": 29.49
}

============================================================
  GET /api/market/symbol-data/{symbol}
============================================================
Status: 200
{
  "equityResponse": [
    {
      "orderBook": {
        "buyPrice1": 0,
        "buyQuantity1": 0,
        "buyPrice2": 0,
        "buyQuantity2": 0,
        "buyPrice3": 0,
        "buyQuantity3": 0,
        "buyPrice4": 0,
        "buyQuantity4": 0,
        "buyPrice5": 0,
        "buyQuantity5": 0,
        "sellPrice1": 0,
        "sellQuantity1": 0,
        "sellPrice2": 0,
        "sellQuantity2": 0,
        "sellPrice3": 0,
        "sellQuantity3": 0,
        "sellPrice4": 0,
        "sellQuantity4": 0,
        "sellPrice5": 0,
        "sellQuantity5": 0,
        "lastPrice": 1418.6,
        "totalBuyQuantity": 0,
        "totalSellQuantity": 0,
        "perBuyQty": 0,
        "perSellQty": 0
      },
      "metaData": {
        "identifier": "RELIANCEEQN",
        "companyName": "Reliance Industries Limited",
        "isinCode": "INE002A01018",
        "symbol": "RELIANCE",
        "series": "EQ",
        "marketType": "N",
        "open": 1375,
        "dayHigh": 1429.4,
        "dayLow": 1370,
        "previousClose": 1404.8,
        "averagePrice": 1404.07,
        "change": 13.8,
        "pChange": 0.98,
        "basePrice": 1404.8,
        "closePrice": 1424,
        "indicativeClose": 0,
        "ic_change": 0,
        "ic_pchange": 0,
        "spoChange": 0,
        "spoPchange": 0,
        "symbolStatus": "NM",
        "adjPrice": 0,
        "iep": 0,
        "ieq": 0
      },
      "tradeInfo": {
        "totalTradedVolume": 24870822,
        "totalTradedValue": 34920375045.54,
        "series": "EQ",
        "lastPrice": 1418.6,
        "issuedSize": 13532472634,
        "basePrice": 1404.8,
        "ffmc": 9551684163543.4,
        "faceValue": 10,
        "impactCost": 0.01,
        "deliveryToTradedQuantity": 47.14,
        "applicableMargin": 12.5,
        "marketLot": null,
        "quantitytraded": 24870822,
        "deliveryquantity": 11723015,
        "totalMarketCap": 19197165678592.4,
        "secwisedelposdate": "09-Mar-2026 00:00:00"
      },
      "priceInfo": {
        "yearHightDt": "05-Jan-2026 00:00:00",
        "yearLowDt": "07-Apr-2025 00:00:00",
        "yearHigh": 1611.8,
        "yearLow": 1114.85,
        "priceBand": "1281.60-1566.40",
        "cmDailyVolatility": "1.32",
        "cmAnnualVolatility": "25.22",
        "tickSize": 0.1,
        "inav": 0,
        "isINav": "False",
        "ppriceBand": "No Band"
      },
      "secInfo": {
        "secStatus": "Listed",
        "listingDate": "29-Nov-1995 00:00:00",
        "pdSectorInd": "NIFTY 500                                         ",
        "pdSectorPe": "19.51",
        "pdSymbolPe": "19.51",
        "isSuspended": "Active",
        "basicIndustry": "Refineries & Marketing",
        "index": "Nifty 50",
        "deliveryQuantity": "11723015",
        "deliveryTotradedQuantity": "47.14",
        "securityvar": "8.23",
        "indexvar": "0",
        "extremelossMargin": "3.5",
        "varMargin": "9",
        "adhocMargin": "0",
        "applicableMargin": "12.5",
        "bondType": null,
        "issueDesc": null,
        "issueDate": null,
        "maturityDate": null,
        "couponRate": null,
        "nxtIpDate": null,
        "creditRating": null,
        "macro": "Energy",
        "sector": "Oil Gas & Consumable Fuels",
        "industryInfo": "Petroleum Products",
        "indexList": [
          "NIFTY 50",
          "NIFTY 100",
          "NIFTY 200",
          "NIFTY 500",
          "NIFTY ALPHA LOW-VOLATILITY 30",
          "NIFTY ALPHA QUALITY VALUE LOW-VOLATILITY 30",
          "NIFTY COMMODITIES",
          "NIFTY CONGLOMERATE 50",
          "NIFTY ENERGY",
          "NIFTY EV & NEW AGE AUTOMOTIVE",
          "NIFTY INDIA FPI 150",
          "NIFTY INDIA MANUFACTURING",
          "NIFTY INDIA SELECT 5 CORPORATE GROUPS (MAATR)",
          "NIFTY INFRASTRUCTURE",
          "NIFTY LARGEMIDCAP 250",
          "NIFTY LOW VOLATILITY 50",
          "NIFTY MOBILITY",
          "NIFTY OIL & GAS",
          "NIFTY TOP 10 EQUAL WEIGHT",
          "NIFTY TOP 15 EQUAL WEIGHT",
          "NIFTY TOP 20 EQUAL WEIGHT",
          "NIFTY TOTAL MARKET",
          "NIFTY100 ENHANCED ESG",
          "NIFTY100 EQUAL WEIGHT",
          "NIFTY100 ESG",
          "NIFTY100 ESG SECTOR LEADERS",
          "NIFTY100 LIQUID 15",
          "NIFTY100 LOW VOLATILITY 30",
          "NIFTY50 EQUAL WEIGHT",
          "NIFTY500 EQUAL WEIGHT",
          "NIFTY500 LARGEMIDSMALL EQUAL-CAP WEIGHTED",
          "NIFTY500 MULTICAP 50:25:25",
          "NIFTY500 MULTICAP INDIA MANUFACTURING 50:30:20",
          "NIFTY500 MULTICAP INFRASTRUCTURE 50:30:20"
        ],
        "boardStatus": "Main",
        "tradingSegment": "Normal Market",
        "sessionNo": null,
        "classShare": "Equity",
        "nameOfComplianceOfficer": null,
        "sddcompliance": null
      },
      "lastUpdateTime": "09-Mar-2026 16:00:00"
    }
  ]
}

============================================================
  GET /api/screener/search
============================================================
Status: 200
Response: List of 9 items
Sample item (first):
{
  "id": 2726,
  "name": "Reliance Industries Ltd",
  "url": "/company/RELIANCE/consolidated/"
}

============================================================
  GET /api/screener/company/{symbol}
============================================================
Status: 200
{
  "symbol": "RELIANCE",
  "name": "Reliance Industries Ltd",
  "screener_warehouse_id": "6598251",
  "ratios": {
    "market_cap": "19,26,475 Cr.",
    "price": "1,424",
    "pe": "25.1",
    "book_value": "648",
    "dividend_yield": "0.39 %",
    "roce": "9.69 %",
    "roe": "8.40 %",
    "face_value": "10.0",
    "high_52w": "1,612",
    "low_52w": "1,115",
    "eps_growth_5years": "9.92%",
    "eps": "61.5",
    "dividend_payout": "10.7%",
    "piotroski_score": "4.00",
    "promoter_holding": "50.0%",
    "roic": "10.6%",
    "total_assets": "20,38,946Cr.",
    "ebit": "1,42,777Cr.",
    "working_capital": "46,670Cr.",
    "sales": "10,24,548Cr."
  },
  "quarters": [
    {
      "period": "Dec 2025",
      "sales": "264,905",
      "net_profit": "22,290",
      "eps": "13.78"
    },
    {
      "period": "Sep 2025",
      "sales": "254,623",
      "net_profit": "22,092",
      "eps": "13.42"
    },
    {
      "period": "Jun 2025",
      "sales": "243,632",
      "net_profit": "30,783",
      "eps": "19.95"
    },
    {
      "period": "Mar 2025",
      "sales": "261,388",
      "net_profit": "22,611",
      "eps": "14.34"
    }
  ]
}

============================================================
  GET /api/screener/trades/{symbol}
============================================================
Status: 200
warehouse_id: 2726
insider_trades: 308 records
Sample record (first):
{
  "period": "Sep 2025",
  "person": "Shobha Agarwal",
  "category": "Immediate Relative",
  "quantity_raw": "-1,25,000",
  "quantity": -125000,
  "direction": "down",
  "avg_price_raw": "1,385",
  "avg_price": 1385,
  "value_raw": "1,731",
  "value": 1731,
  "value_in": "lacs",
  "small_quantity": true
}
bulk_deals: 25 records
Sample record (first):
{
  "period": "27 Mar 2020",
  "person": "Tattvam Enterprises Llp",
  "category": "",
  "quantity_raw": "B",
  "quantity": null,
  "direction": null,
  "avg_price_raw": "7,67,35,388",
  "avg_price": 76735388,
  "value_raw": "1,056",
  "value": 1056,
  "value_in": "price",
  "small_quantity": false
}
block_deals: 297 records
Sample record (first):
{
  "period": "27 Jan 2026",
  "person": "Morgan Stanley Asia (Singapore) Pte.",
  "category": "",
  "quantity_raw": "Sale",
  "quantity": null,
  "direction": null,
  "avg_price_raw": "11,51,736",
  "avg_price": 1151736,
  "value_raw": "1,384",
  "value": 1384,
  "value_in": "price",
  "small_quantity": false
}

============================================================
  GET /api/ai/health
============================================================
Status: 200
{
  "status": "ready",
  "model": "gemma-2-9b"
}

============================================================
  POST /api/ai/summarize
============================================================
Using data from: GET /api/corporatefilings/RELIANCE
Status: 200
Response: JSON with summary
{
  "summary": "## Quarterly Financial Statement Analysis - [Company Name]\n\n**Opening Statement:** This looks like a standard quarterly financial statement for [Company Name], covering the period ended December 31, 2024. The report provides key financial data including revenue, expenses, profitability, and basic earnings per share.\n\n**Executive Summary:**  [Company Name] reported **Total Income of \u20b913,147,400** for the quarter ended December 31, 2024. This represents a **QoQ decrease of -4.0%** compared to the previous quarter's \u20b913,785,500.  Profit After Tax (PAT) stood at **\u20b9872,100**, indicating a **QoQ decline of -10.6%**.\n\n**Section 1: Revenue & Income Trends:**\n\n| Metric | Q4 2024 | Q3 2024 | Q2 2024 | Q1 2024 | Q4 2023 |\n|---|---|---|---|---|---|\n| **Revenue from Operations** | \u20b912,826,000 | \u20b913,405,400 | \u20b913,433,100 | \u20b915,101,400 | \u20b913,057,900 |\n| **YoY Change (Revenue from Operations)** |  -12.4% | -12.4% | -12.4% | -12.4% | \n| **QoQ Change (Revenue from Operations)** | -4.0% | 0.2% | 0.2% | 0.2% |\n\n**Section 2: Expense Analysis:**\n\n*  The largest expense category was **Other Expenses**, accounting for **\u20b91,948,600** in Q4 2024. This represents a **QoQ increase of 1.7%**.\n* **Employee Benefits Expense** also saw a notable rise, increasing by **3.7% QoQ** to \u20b9218,100.\n*  **Finance Costs** decreased by **-10.6% QoQ** to \u20b9237,100.\n\n**Section 3: Profitability & Margins:**\n\n| Metric | Q4 2024 | Q3 2024 |\n|---|---|---|\n| **PBT (Profit Before Tax)** | \u20b91,159,700 | \u20b91,021,400 |\n| **Net Profit (PAT)** | \u20b9872,100 | \u20b9771,300 |\n| **Basic EPS** | \u20b96.44 | \u20b911.4 |\n\n*Note: This analysis does not include details on specific tax impacts or one-off items that may have affected the reported figures.*\n\n\n**Section 4: Key Financial Ratios:**\n\n* **EBITDA Margin:**  (To be calculated based on provided data)\n* **Net Profit Margin:** (To be calculated based on provided data)\n\nThe company's efficiency can be further assessed by analyzing its working capital management, inventory turnover, and days sales outstanding.\n\n\n**Section 5: Investor Perspective:**\n\n* **YoY Growth:** Revenue grew by -12.4% year-on-year, indicating a challenging operating environment.\n* **Changes in Equity Base/Share Capital:** The paid-up equity share capital remained stable at \u20b91,353,200.\n* **Debt Position:**  The company's debt position is not readily apparent from the provided data. Further analysis of the \"Details of Debt Securities\" section would be required to assess its leverage.\n\n**Closing:** I can provide you with specific growth percentages for different line items or compare these figures against industry benchmarks and competitors upon request. Please let me know if you have any further questions or require additional analysis.",
  "input_tokens": 2352,
  "output_tokens": 861,
  "model": "google/gemma-2-9b"
}

============================================================
  END OF DOCUMENTATION
============================================================