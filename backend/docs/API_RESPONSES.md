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
Response: List of 2253 items
Sample item (first):
{
  "symbol": "20MICRONS",
  "companyName": "20 Microns Limited",
  "segment": "EQUITY",
  "industry": "Industrial Minerals",
  "sectorPE": 8.86,
  "symbolPE": 8.91,
  "industryInfo": {
    "macro": "Commodities",
    "sector": "Metals & Mining",
    "industry": "Minerals & Mining",
    "basicIndustry": "Industrial Minerals"
  },
  "lastUpdateTime": "2026-03-10T14:31:25",
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
  "sectorPE": 19.78,
  "symbolPE": 19.78,
  "industryInfo": {
    "macro": "Energy",
    "sector": "Oil Gas & Consumable Fuels",
    "industry": "Petroleum Products",
    "basicIndustry": "Refineries & Marketing"
  },
  "lastUpdateTime": "2026-03-10T16:00:00",
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
  "lastUpdateTime": "2026-03-10T16:00:00",
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
  "symbol": "PREMIERENE",
  "identifier": "",
  "series": "EQ",
  "open": "749",
  "dayHigh": "795",
  "dayLow": "747.75",
  "lastPrice": "785",
  "previousClose": "747.75",
  "change": 37.25,
  "pChange": 4.98,
  "totalTradedVolume": 5224183,
  "totalTradedValue": 4071623746.54,
  "yearHigh": "1163.9",
  "yearLow": "660",
  "nearWKH": 32.55434315662858,
  "nearWKL": -18.939393939393938,
  "perChange365d": -12.16,
  "perChange30d": -0.94,
  "date365dAgo": "10-Mar-2025",
  "date30dAgo": "06-Feb-2026",
  "chartTodayPath": "https://nsearchives.nseindia.com/today/PREMIERENEEQN.svg",
  "chart30dPath": "https://nsearchives.nseindia.com/30d/PREMIERENE-EQ.svg",
  "chart365dPath": "https://nsearchives.nseindia.com/365d/PREMIERENE-EQ.svg",
  "meta": {
    "symbol": "PREMIERENE",
    "companyName": "Premier Energies Limited",
    "industry": "Other Electrical Equipment",
    "activeSeries": [
      "EQ"
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
    "isin": "INE0BS701011",
    "slb_isin": "INE0BS701011",
    "listingDate": "2024-09-03",
    "isMunicipalBond": false,
    "isHybridSymbol": false,
    "segment": "EQUITY",
    "quotepreopenstatus": {
      "equityTime": "11-Mar-2026 16:00:00",
      "preOpenTime": "11-Mar-2026 09:07:27",
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
  "symbol": "COLPAL",
  "identifier": "",
  "series": "EQ",
  "open": "2198.3",
  "dayHigh": "2198.3",
  "dayLow": "2046",
  "lastPrice": "2051",
  "previousClose": "2198.3",
  "change": -147.3,
  "pChange": -6.7,
  "totalTradedVolume": 1659346,
  "totalTradedValue": 3470721280.52,
  "yearHigh": "2747.4",
  "yearLow": "2029.4",
  "nearWKH": 25.34760136856665,
  "nearWKL": -1.0643539962550461,
  "perChange365d": -15.77,
  "perChange30d": -3.64,
  "date365dAgo": "10-Mar-2025",
  "date30dAgo": "06-Feb-2026",
  "chartTodayPath": "https://nsearchives.nseindia.com/today/COLPALEQN.svg",
  "chart30dPath": "https://nsearchives.nseindia.com/30d/COLPAL-EQ.svg",
  "chart365dPath": "https://nsearchives.nseindia.com/365d/COLPAL-EQ.svg",
  "meta": {
    "symbol": "COLPAL",
    "companyName": "Colgate Palmolive (India) Limited",
    "industry": "Personal Care",
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
    "isin": "INE259A01022",
    "slb_isin": "INE259A01022",
    "listingDate": "2007-12-17",
    "isMunicipalBond": false,
    "isHybridSymbol": false,
    "segment": "EQUITY",
    "quotepreopenstatus": {
      "equityTime": "11-Mar-2026 16:00:00",
      "preOpenTime": "11-Mar-2026 09:07:27",
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
Response: List of 91 items
Sample item (first):
{
  "date": "10-Mar-2026",
  "symbol": "ABB",
  "name": "ABB LTD.",
  "clientName": null,
  "buySell": null,
  "qty": "50",
  "watp": null,
  "remarks": null
}

============================================================
  GET /api/market/change-ranges/{symbol}
============================================================
Status: 200
{
  "oneDayPercent": -11.98,
  "oneWeekPercent": 3.11,
  "oneMonthPercent": -5.58,
  "threeMonthPercent": -10.24,
  "sixMonthPercent": 0.25,
  "oneYearPercent": 11.18,
  "twoYearPercent": -5.44,
  "threeYearPercent": 19.41,
  "fiveYearPercent": 27.12
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
        "lastPrice": 1386.8,
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
        "open": 1424.9,
        "dayHigh": 1434,
        "dayLow": 1383.6,
        "previousClose": 1408.8,
        "averagePrice": 1402.94,
        "change": -22,
        "pChange": -1.56,
        "basePrice": 1408.8,
        "closePrice": 1390.2,
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
        "totalTradedVolume": 21848087,
        "totalTradedValue": 30651555175.78,
        "series": "EQ",
        "lastPrice": 1386.8,
        "issuedSize": 13532472634,
        "basePrice": 1408.8,
        "ffmc": 9337569151277.31,
        "faceValue": 10,
        "impactCost": 0.01,
        "deliveryToTradedQuantity": 45.03,
        "applicableMargin": 12.5,
        "marketLot": null,
        "quantitytraded": 21848087,
        "deliveryquantity": 9837323,
        "totalMarketCap": 18766833048831.2,
        "secwisedelposdate": "11-Mar-2026 00:00:00"
      },
      "priceInfo": {
        "yearHightDt": "05-Jan-2026 00:00:00",
        "yearLowDt": "07-Apr-2025 00:00:00",
        "yearHigh": 1611.8,
        "yearLow": 1114.85,
        "priceBand": "1268.00-1549.60",
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
        "pdSectorPe": "19.57",
        "pdSymbolPe": "19.57",
        "isSuspended": "Active",
        "basicIndustry": "Refineries & Marketing",
        "index": "Nifty 50",
        "deliveryQuantity": "9837323",
        "deliveryTotradedQuantity": "45.03",
        "securityvar": "8.22",
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
      "lastUpdateTime": "11-Mar-2026 16:00:00"
    }
  ]
}

============================================================
  GET /api/market/52week-low
============================================================
Status: 200
Top-level keys: ['data', 'low', 'timestamp']
data: List of 140 items
Sample item (first):
{
  "symbol": "ABSLLIQUID",
  "series": "EQ",
  "comapnyName": "Aditya Birla Sun Life CRISIL Liquid Overnight ETF",
  "new52WHL": 999.99,
  "prev52WHL": 999.99,
  "prevHLDate": "10-Mar-2026",
  "ltp": 999.99,
  "prevClose": "999.99",
  "change": 0,
  "pChange": 0
}

============================================================
  GET /api/market/52week-high
============================================================
Status: 200
Top-level keys: ['high', 'data', 'timestamp']
data: List of 32 items
Sample item (first):
{
  "symbol": "ABB",
  "series": "EQ",
  "comapnyName": "ABB India Limited",
  "new52WHL": 6325,
  "prev52WHL": 6260,
  "prevHLDate": "10-Jun-2025",
  "ltp": 6268.5,
  "prevClose": "6224.5",
  "change": 44,
  "pChange": 0.7068840870752671
}

============================================================
  GET /api/market/volume-gainers
============================================================
Status: 200
Top-level keys: ['data', 'timestamp']
data: List of 25 items
Sample item (first):
{
  "symbol": "GSEC10ABSL",
  "companyName": "AdityaBirlaSunLifeMF - Aditya Birla Sun Life CRISIL 10 Year Gilt ETF",
  "volume": 64363,
  "week1AvgVolume": 10866,
  "week1volChange": 5.923338855144487,
  "week2AvgVolume": 6624,
  "week2volChange": 9.716343105582562,
  "ltp": 111.29,
  "pChange": -0.12,
  "turnover": 71.13398
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
    "market_cap": "18,80,950 Cr.",
    "price": "1,390",
    "pe": "24.5",
    "book_value": "648",
    "dividend_yield": "0.40 %",
    "roce": "9.69%",
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
    "sales": "10,24,548Cr.",
    "return_on_equity": "8.40%",
    "debt_to_equity": "0.43",
    "sales_growth": "9.01%",
    "profit_growth": "10.9%",
    "sales_growth_5years": "10.0%",
    "profit_var_5yrs": "9.93%",
    "change_in_prom_hold": "0.00%"
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
  "status": "unconfigured",
  "model": null
}

============================================================
  POST /api/ai/summarize
============================================================
Using data from: GET /api/corporatefilings/RELIANCE
Status: 503
Response: Model still loading (503 Service Unavailable)
{
  "_error": "Upstream error",
  "_status": 503
}

============================================================
  END OF DOCUMENTATION
============================================================