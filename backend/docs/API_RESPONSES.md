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
Response: List of 2255 items
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
  GET /api/watchlist
============================================================
Status: 200
Response: List of 24 items
Sample item (first):
{
  "id": 1,
  "symbol": "IDFCFIRSTB",
  "exchange": "NSE",
  "created_at": "2026-03-09T19:16:45.049000"
}

============================================================
  POST /api/watchlist
============================================================
Status: 201
{
  "id": 25,
  "symbol": "TCS",
  "exchange": "NSE",
  "created_at": "2026-03-14T17:11:30"
}

============================================================
  DELETE /api/watchlist/{id}
============================================================
Status: 200
{
  "ok": true
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
  "symbol": "SYNGENE",
  "identifier": "",
  "series": "EQ",
  "open": "405.9",
  "dayHigh": "428",
  "dayLow": "405",
  "lastPrice": "420.6",
  "previousClose": "404.1",
  "change": 16.5,
  "pChange": 4.08,
  "totalTradedVolume": 9786652,
  "totalTradedValue": 4136328467.8,
  "yearHigh": "760",
  "yearLow": "387.05",
  "nearWKH": 44.6578947368421,
  "nearWKL": -8.668130732463508,
  "perChange365d": -36.83,
  "perChange30d": -7.53,
  "date365dAgo": "13-Mar-2025",
  "date30dAgo": "11-Feb-2026",
  "chartTodayPath": "https://nsearchives.nseindia.com/today/SYNGENEEQN.svg",
  "chart30dPath": "https://nsearchives.nseindia.com/30d/SYNGENE-EQ.svg",
  "chart365dPath": "https://nsearchives.nseindia.com/365d/SYNGENE-EQ.svg",
  "meta": {
    "symbol": "SYNGENE",
    "companyName": "Syngene International Limited",
    "industry": "Healthcare Research Analytics & Technology",
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
    "isin": "INE398R01022",
    "slb_isin": "INE398R01022",
    "listingDate": "2015-08-11",
    "isMunicipalBond": false,
    "isHybridSymbol": false,
    "segment": "EQUITY",
    "quotepreopenstatus": {
      "equityTime": "13-Mar-2026 16:00:00",
      "preOpenTime": "13-Mar-2026 09:07:56",
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
  "symbol": "LT",
  "identifier": "",
  "series": "EQ",
  "open": "3696",
  "dayHigh": "3697",
  "dayLow": "3424.5",
  "lastPrice": "3445",
  "previousClose": "3719.5",
  "change": -274.5,
  "pChange": -7.38,
  "totalTradedVolume": 10778730,
  "totalTradedValue": 37845953414.1,
  "yearHigh": "4440",
  "yearLow": "2965.3",
  "nearWKH": 22.40990990990991,
  "nearWKL": -16.177115300306877,
  "perChange365d": 7.9,
  "perChange30d": -17.54,
  "date365dAgo": "13-Mar-2025",
  "date30dAgo": "11-Feb-2026",
  "chartTodayPath": "https://nsearchives.nseindia.com/today/LTEQN.svg",
  "chart30dPath": "https://nsearchives.nseindia.com/30d/LT-EQ.svg",
  "chart365dPath": "https://nsearchives.nseindia.com/365d/LT-EQ.svg",
  "meta": {
    "symbol": "LT",
    "companyName": "Larsen & Toubro Limited",
    "industry": "Civil Construction",
    "activeSeries": [
      "EQ"
    ],
    "debtSeries": [],
    "isFNOSec": true,
    "isCASec": false,
    "isSLBSec": true,
    "isDebtSec": true,
    "isSuspended": false,
    "tempSuspendedSeries": [],
    "isETFSec": false,
    "isDelisted": false,
    "isin": "INE018A01030",
    "slb_isin": "INE018A01030",
    "listingDate": "2004-06-23",
    "isMunicipalBond": false,
    "isHybridSymbol": false,
    "segment": "EQUITY",
    "quotepreopenstatus": {
      "equityTime": "13-Mar-2026 16:00:00",
      "preOpenTime": "13-Mar-2026 09:07:56",
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
Response: List of 115 items
Sample item (first):
{
  "date": "12-Mar-2026",
  "symbol": "AAVAS",
  "name": "AAVAS FINANCIERS LIMITED",
  "clientName": null,
  "buySell": null,
  "qty": "1",
  "watp": null,
  "remarks": null
}

============================================================
  GET /api/market/change-ranges/{symbol}
============================================================
Status: 200
{
  "oneDayPercent": -12.28,
  "oneWeekPercent": -1.62,
  "oneMonthPercent": -2.64,
  "threeMonthPercent": -11.2,
  "sixMonthPercent": -0.92,
  "oneYearPercent": 10.75,
  "twoYearPercent": -3.5,
  "threeYearPercent": 21.0,
  "fiveYearPercent": 29.31
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
        "lastPrice": 1382.1,
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
        "open": 1385.2,
        "dayHigh": 1400.8,
        "dayLow": 1378.4,
        "previousClose": 1392.2,
        "averagePrice": 1388.24,
        "change": -10.1,
        "pChange": -0.73,
        "basePrice": 1392.2,
        "closePrice": 1380.7,
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
        "totalTradedVolume": 17265090,
        "totalTradedValue": 23968088541.6,
        "series": "EQ",
        "lastPrice": 1382.1,
        "issuedSize": 13532472634,
        "basePrice": 1392.2,
        "ffmc": 9305923221791.44,
        "faceValue": 10,
        "impactCost": 0.01,
        "deliveryToTradedQuantity": 47.97,
        "applicableMargin": 12.5,
        "marketLot": null,
        "quantitytraded": 17265090,
        "deliveryquantity": 8282491,
        "totalMarketCap": 18703230427451.4,
        "secwisedelposdate": "13-Mar-2026 00:00:00"
      },
      "priceInfo": {
        "yearHightDt": "05-Jan-2026 00:00:00",
        "yearLowDt": "07-Apr-2025 00:00:00",
        "yearHigh": 1611.8,
        "yearLow": 1114.85,
        "priceBand": "1242.70-1518.70",
        "cmDailyVolatility": "1.31",
        "cmAnnualVolatility": "25.03",
        "tickSize": 0.1,
        "inav": 0,
        "isINav": "False",
        "ppriceBand": "No Band"
      },
      "secInfo": {
        "secStatus": "Listed",
        "listingDate": "29-Nov-1995 00:00:00",
        "pdSectorInd": "NIFTY 500                                         ",
        "pdSectorPe": "19.34",
        "pdSymbolPe": "19.34",
        "isSuspended": "Active",
        "basicIndustry": "Refineries & Marketing",
        "index": "Nifty 50",
        "deliveryQuantity": "8282491",
        "deliveryTotradedQuantity": "47.97",
        "securityvar": "8.19",
        "indexvar": "0",
        "extremelossMargin": "3.5",
        "varMargin": "9",
        "adhocMargin": "0",
        "applicableMargin": "12.5",
        "bondType": null,
        "issueDesc": "Reliance Industries Ltd",
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
      "lastUpdateTime": "13-Mar-2026 16:00:00"
    }
  ]
}

============================================================
  GET /api/market/52week-low
============================================================
Status: 200
Top-level keys: ['data', 'low', 'timestamp']
data: List of 509 items
Sample item (first):
{
  "symbol": "20MICRONS",
  "series": "EQ",
  "comapnyName": "20 Microns Limited",
  "new52WHL": 156.35,
  "prev52WHL": 160,
  "prevHLDate": "09-Mar-2026",
  "ltp": 157.94,
  "prevClose": "163.09",
  "change": -5.15,
  "pChange": -3.1577656508676193
}

============================================================
  GET /api/market/52week-high
============================================================
Status: 200
Top-level keys: ['high', 'data', 'timestamp']
data: List of 18 items
Sample item (first):
{
  "symbol": "ABB",
  "series": "EQ",
  "comapnyName": "ABB India Limited",
  "new52WHL": 6554,
  "prev52WHL": 6429.5,
  "prevHLDate": "12-Mar-2026",
  "ltp": 6389,
  "prevClose": "6409",
  "change": -20,
  "pChange": -0.31206116398814165
}

============================================================
  GET /api/market/volume-gainers
============================================================
Status: 200
Top-level keys: ['data', 'timestamp']
data: List of 25 items
Sample item (first):
{
  "symbol": "ZYDUSWELL",
  "companyName": "Zydus Wellness Limited",
  "volume": 48286539,
  "week1AvgVolume": 8114410,
  "week1volChange": 5.950714105039255,
  "week2AvgVolume": 4932643,
  "week2volChange": 9.789180394278224,
  "ltp": 412.05,
  "pChange": 5.95,
  "turnover": 205971.06075
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
    "market_cap": "18,68,898 Cr.",
    "price": "1,381",
    "pe": "24.4",
    "book_value": "648",
    "dividend_yield": "0.40%",
    "roce": "9.69%",
    "roe": "8.40 %",
    "face_value": "10.0",
    "high_52w": "1,612",
    "low_52w": "1,115",
    "eps_growth_5years": "9.92%",
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
    "opm": "17.4%",
    "profit_after_tax": "76,747Cr.",
    "mar_cap": "18,68,898Cr.",
    "sales_qtr": "2,64,905Cr.",
    "price_to_earning": "24.4",
    "price_to_book_value": "2.13",
    "industry_pe": "14.1",
    "current_price": "1,381",
    "price_to_sales": "1.82",
    "peg_ratio": "4.53",
    "pat_qtr": "18,645Cr.",
    "qtr_sales_var": "10.4%",
    "qtr_profit_var": "0.57%",
    "pledged_percentage": "0.00%",
    "debt": "3,74,593Cr.",
    "eps": "61.5",
    "evebitda": "10.7",
    "sales_last_year": "9,62,820Cr.",
    "op_ann": "1,65,598Cr.",
    "ebidt_last_year": "1,82,019Cr.",
    "dep_ann": "53,136Cr.",
    "ebit_last_year": "1,28,883Cr.",
    "pbt_ann": "1,06,017Cr.",
    "interest_last_year": "24,269Cr.",
    "tax_last_year": "25,230Cr.",
    "pat_ann": "68,732Cr.",
    "rsi": "43.2",
    "macd": "-12.9",
    "market_cap_to_sales": "1.82",
    "debt_to_profit": "4.61",
    "graham": "947",
    "altman_z_score": "2.83",
    "chg_in_fii_hold": "0.44%",
    "chg_in_dii_hold": "-0.15%",
    "earnings_yield": "6.70%"
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
  GET /api/screener/quarterly/{symbol}
============================================================
Status: 200
symbol: RELIANCE
consolidated: True
quarterly_results: 4 year(s)
Sample year (2022):
{
  "Dec": {
    "Sales": "216,737",
    "Expenses": "181,728",
    "Operating Profit": "35,009",
    "OPM %": "16%",
    "Other Income": "3,377",
    "Interest": "5,201",
    "Depreciation": "10,183",
    "Profit before tax": "23,002",
    "Tax %": "23%",
    "Net Profit": "17,806",
    "EPS in Rs": "11.67",
    "Raw PDF": null
  }
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
  GET /api/news/global
============================================================
Status: 200
Response: List of 169 items
Sample item (first):
{
  "url": "https://www.moneycontrol.com/news/brand-connect/the-digital-leapfrog-why-the-next-era-of-economic-agency-for-women-is-on-chain-13860050.html",
  "source": "moneycontrol_global",
  "title": "The Digital Leapfrog: Why the Next Era of Economic Agency for Women is On-Chain",
  "text": "For decades, financial inclusion was measured in small wins: a bank account opened, a microloan disbursed, a woman added to the ledger. Those wins mattered. But in 2026, the question has fundamentally changed. We are no longer asking whether women can access the financial system. We are asking whether the financial system, now being rebuilt from the ground up on blockchain infrastructure will be designed with them in mind.\n\nThe answer is not inevitable. It is a choice. And it is one that the digital assets industry must make deliberately, or risk hard-coding the same exclusions into a new architecture.\n\nAs we hit the midpoint of this decade, the narrative of financial inclusion has shifted. In the age of digital assets and Web3, we have the tools to bypass the systemic bottlenecks that have historically sidelined women.\n\nThe Remittance Revolution\n\nIn the traditional world, the \"pink tax\" is literal. Consider remittances - an $800 billion industry where the stakes are anything but abstract. Women represent a significant share of global remittance senders, often sustaining households and entire local economies from abroad. Yet the traditional system has consistently worked against them: high fees, predatory exchange rates, and the physical risk of carrying cash to brick-and-mortar transfer points. Yet, they face disproportionate hurdles: higher fees, predatory exchange rates, and the physical safety risks of carrying cash to brick-and-mortar transfer points.\n\nBy utilizing stablecoins and peer-to-peer networks, a Filipina domestic worker in Dubai or a software consultant in Singapore can send value home instantly, for a fraction of the legacy cost. This isn't \"disruption\"as a taking point; it is the liberation of billions of dollars in household wealth that was previously swallowed by intermediaries. This is \"crypto-utility\" in its purest form: putting more value back into the hands of the women who earned it. If crypto has a killer use case, this is it.\n\nBeyond \"Boutique\" Inclusion\n\nThe critique of traditional micro-finance was often its scale - it was \"boutique,\" limited by local geography and high interest rates. Digital finance removes the borders.\n\nIn the Web3 era, a female entrepreneur in Vietnam or Sub-Saharan Africa no longer needs a traditional bank credit score; she can now overcome conventional credit biases by leveraging decentralized finance (DeFi).\n\nBridging the \"Confidence Gap\"\n\nDespite the technical parity of the blockchain, a social hurdle remains. Data suggests that while women are more risk-aware investors, they are also more likely to stay on the sidelines if their understanding is limited.\n\nTo move from \"participation\" to \"power,\" we must address three critical frontiers:\n\nEducation as an Equity Tool: Financial literacy is the ultimate gateway. Programs like the Binance Academy are not \"nice-to-haves\" - they are essential infrastructure.\n\nSafety as a Feature: We must champion rigorous regulatory compliance. By working within the \"guardrails\" set by bodies like ADGM in Dubai, we provide the institutional-grade stability that female participants demand before moving their family\u2019s future onto the chain. For a woman managing a family's life savings, \"security\"isn'ta buzzword - it\u2019s the prerequisite for entry.\n\nDismantling \"Algorithm Bias\": Traditional finance often relies on legacy data that reflects decades of gender-based economic disparity. Digital finance offers a \"clean slate,\" but only if we are intentional. We must ensure that the AI and algorithmic models powering the next generation of credit and lending are audited for the very biases they were meant to solve.\n\nThe \"Last Mile\" of Mobile Access: In many parts of the world, women are still less likely than men to own a smartphone or have reliable internet. True inclusion in digital finance requires us to partner with government and infrastructure providers to ensure that the \"borderless\" economydoesn't stop at the doorstep of those without the latest hardware.\n\nVisible Leadership: You cannot be what you cannot see. We are committed to ensuring that the architects of the new financial internet reflect the diversity of the people using it. At Binance, women nowrepresent40% of the leadership team.\n\nThe 2026 Mandate\n\nDigital assets are becoming the plumbing of the global economy. The decisions being made right now about who participates, who leads, and what assumptions get coded into the underlying protocols will shape financial outcomes for a generation.\n\nThe evidence on what happens when women are financially empowered is unambiguous: they reinvest at higher rates into families and communities, driving GDP growth and social stability. Female investors also tend to bring a longer time horizon and utility-focused discipline to markets that have been chronically short-termist. This industry needs that perspective urgently.\n\nThe 20th-century bank had an invisible ceiling. The open ledger of the 21st century doesn't have to.\n\nThe question for every platform, protocol, and policymaker is no longer whether women will join this economy. It is whether what we are building is worthy of their participation.\n\nMoneycontrol Journalists are not involved in creation of this article",
  "authors": null,
  "top_image": "https://images.moneycontrol.com/static-mcnews/2026/03/20260313191851_feature1.jpg",
  "publish_date": "2026-03-14T00:57:22",
  "fetched_at": "2026-03-13T19:59:33.712501",
  "created_at": "2026-03-13T20:00:43",
  "company_symbol": null
}

============================================================
  GET /api/news/company/{symbol}
============================================================
Status: 200
Response: List of 5 items
Sample item (first):
{
  "url": "https://www.moneycontrol.com/news/business/stocks/buy-reliance-industries-target-of-rs-1750-motilal-oswal-2-13858981.html",
  "source": "moneycontrol_company",
  "title": "Buy Reliance Industries; target of Rs 1750: Motilal Oswal",
  "text": "Buy Reliance Industries; target of Rs 1750: Motilal OswalMotilal Oswal is bullish on Reliance Industries recommended buy rating on the stock with a target price of Rs 1750 in its research report dated March 12, 2026.Broker ResearchMarch 13, 2026/ 09:34 ISTBuyRIRIWatchlistPortfolioMessageFollowNSE/BSE SelectNSE LIVEBSE LIVETradeDay HighDay LowVolume (NSE)More\u00d7Add to Watchlist\u00d7Motilal Oswal's research report onReliance IndustriesBlockade of the Strait of Hormuz (SoH) (~20% of global oil/LNG supply), ~3-4mb/d of refining capacity disruptions, refined product export restrictions in China, and decade-high crude freight rates have lifted gasoil/gasoline/jet fuel cracks to USD42/16/58 per bbl in Mar\u201926\u2019TD, 147%/40%/124% above LTA. PE and PX prices also rose 10-15% MoM in Mar\u201926\u2019TD. We believe that even if tensions ease soon, supply chain normalization may lag, keeping product cracks elevated and supporting Reliance Industries\u2019 (RIL) refiningpetchem margins.Story continues below AdvertisementRemove AdOutlookWe assign INR174/sh to the New Energy business, INR30/share equity value to RCPL, and INR26/sh to RIL\u2019s stake in JioStar. We reiterate our BUY rating with a TP of INR1,750.For all recommendations report,click hereRelated StoriesBuy VA Tech Wabag; target of Rs 1900: Motilal OswalBuy Hindustan Copper; target of Rs 650: Anand RathiBuy Aditya Infotech; target of Rs 1850: ICICI SecuritiesDisclaimer:\u00a0The views and investment tips expressed by investment experts/broking houses/rating agencies on moneycontrol.com are their own, and not that of the website or its management. Moneycontrol.com advises users to check with certified experts before taking any investment decisions.Reliance Industries - 1303026 - motiBroker Researchfirst published: Mar 13, 2026 09:33 amDiscover the latestBusiness News,Sensex, andNiftyupdates. ObtainPersonal Financeinsights, tax queries, and expert opinions onMoneycontrolor download theMoneycontrol Appto stay updated!AdvertisementRemove AdSubscribe toTech NewslettersAl Edge NewsletterOn SaturdaysFind the best of Al News in one place, specially curated for you every\n        weekend.MC Tech 3 NewsletterDaily-WeekdaysStay on top of the latest tech trends and biggest startup news.Email addressSubscribeTrending newsBengaluru student offers Rs 15,000 to hire \u2018fake parent\u2019 for PTM, leaves internet in splits'Rs 25 crore in FD': Man shares how uncle turned Rs 60,000 land into Rs 14.5 lakh monthly income\u2018Why are you roasting CBSE\u2019: YouTube shares QR code for students after Class 12 maths paper controversyBadshah receives death threat note from Lawrence Bishnoi's gang after Panipat firing: 'Next time, will put a bullet through your forehead'Happy Birthday Aamir Khan: Times when he proved he is Bollywood\u2019s Mr. Perfectionist1st IITian Chief Minister of India: 25 Years, 4 Terms, 0 Corruption \u2014 the Manohar Parrikar storyIndian billionaire who donated Rs 6000 crore to his employees: He runs Rs 1.5 lakh crore company but owns no phone or luxury carScientists discover a massive 26 kg viper in Greece that weighs three times more than a king cobraKaradaiyan Nombu 2026 date and time: When will Savitri vratham be observed? Know manjal saradu muhurtham, rituals and significancePrajakta Koli calls Bruges a real-life fairytale place: 8 magical spots to explore in Belgium\u2019s UNESCO city10 mistakes to avoid when buying a new Induction cooktop\u201cIG is a drug\u201d: US jury set to deliberate in landmark social media addiction trial against Meta and YouTube8 best exercises for people over 40 to keep joints healthy4 best cookware suitable for induction cooking, plus 6 that won\u2019t work5 Feng Shui paintings to attract wealth and good luck into your home",
  "authors": null,
  "top_image": "https://images.moneycontrol.com/static-mcnews/2025/11/20251118070809_Buy_1280x720_3.png",
  "publish_date": null,
  "fetched_at": "2026-03-14T05:04:40.456852",
  "created_at": "2026-03-13T22:19:14",
  "company_symbol": "RELIANCE"
}

============================================================
  POST /api/news/company
============================================================
Status: 200
Response: List of 5 items
Sample item (first):
{
  "url": "https://www.moneycontrol.com/news/business/stocks/buy-reliance-industries-target-of-rs-1750-motilal-oswal-2-13858981.html",
  "source": "moneycontrol_company",
  "title": "Buy Reliance Industries; target of Rs 1750: Motilal Oswal",
  "text": "Buy Reliance Industries; target of Rs 1750: Motilal OswalMotilal Oswal is bullish on Reliance Industries recommended buy rating on the stock with a target price of Rs 1750 in its research report dated March 12, 2026.Broker ResearchMarch 13, 2026/ 09:34 ISTBuyRIRIWatchlistPortfolioMessageFollowNSE/BSE SelectNSE LIVEBSE LIVETradeDay HighDay LowVolume (NSE)More\u00d7Add to Watchlist\u00d7Motilal Oswal's research report onReliance IndustriesBlockade of the Strait of Hormuz (SoH) (~20% of global oil/LNG supply), ~3-4mb/d of refining capacity disruptions, refined product export restrictions in China, and decade-high crude freight rates have lifted gasoil/gasoline/jet fuel cracks to USD42/16/58 per bbl in Mar\u201926\u2019TD, 147%/40%/124% above LTA. PE and PX prices also rose 10-15% MoM in Mar\u201926\u2019TD. We believe that even if tensions ease soon, supply chain normalization may lag, keeping product cracks elevated and supporting Reliance Industries\u2019 (RIL) refiningpetchem margins.Story continues below AdvertisementRemove AdOutlookWe assign INR174/sh to the New Energy business, INR30/share equity value to RCPL, and INR26/sh to RIL\u2019s stake in JioStar. We reiterate our BUY rating with a TP of INR1,750.For all recommendations report,click hereRelated StoriesBuy VA Tech Wabag; target of Rs 1900: Motilal OswalBuy Hindustan Copper; target of Rs 650: Anand RathiBuy Aditya Infotech; target of Rs 1850: ICICI SecuritiesDisclaimer:\u00a0The views and investment tips expressed by investment experts/broking houses/rating agencies on moneycontrol.com are their own, and not that of the website or its management. Moneycontrol.com advises users to check with certified experts before taking any investment decisions.Reliance Industries - 1303026 - motiBroker Researchfirst published: Mar 13, 2026 09:33 amDiscover the latestBusiness News,Sensex, andNiftyupdates. ObtainPersonal Financeinsights, tax queries, and expert opinions onMoneycontrolor download theMoneycontrol Appto stay updated!AdvertisementRemove AdSubscribe toTech NewslettersAl Edge NewsletterOn SaturdaysFind the best of Al News in one place, specially curated for you every\n        weekend.MC Tech 3 NewsletterDaily-WeekdaysStay on top of the latest tech trends and biggest startup news.Email addressSubscribeTrending newsBengaluru student offers Rs 15,000 to hire \u2018fake parent\u2019 for PTM, leaves internet in splits'Rs 25 crore in FD': Man shares how uncle turned Rs 60,000 land into Rs 14.5 lakh monthly income\u2018Why are you roasting CBSE\u2019: YouTube shares QR code for students after Class 12 maths paper controversyBadshah receives death threat note from Lawrence Bishnoi's gang after Panipat firing: 'Next time, will put a bullet through your forehead'Happy Birthday Aamir Khan: Times when he proved he is Bollywood\u2019s Mr. Perfectionist1st IITian Chief Minister of India: 25 Years, 4 Terms, 0 Corruption \u2014 the Manohar Parrikar storyIndian billionaire who donated Rs 6000 crore to his employees: He runs Rs 1.5 lakh crore company but owns no phone or luxury carScientists discover a massive 26 kg viper in Greece that weighs three times more than a king cobraKaradaiyan Nombu 2026 date and time: When will Savitri vratham be observed? Know manjal saradu muhurtham, rituals and significancePrajakta Koli calls Bruges a real-life fairytale place: 8 magical spots to explore in Belgium\u2019s UNESCO city10 mistakes to avoid when buying a new Induction cooktop\u201cIG is a drug\u201d: US jury set to deliberate in landmark social media addiction trial against Meta and YouTube8 best exercises for people over 40 to keep joints healthy4 best cookware suitable for induction cooking, plus 6 that won\u2019t work5 Feng Shui paintings to attract wealth and good luck into your home",
  "authors": null,
  "top_image": "https://images.moneycontrol.com/static-mcnews/2025/11/20251118070809_Buy_1280x720_3.png",
  "publish_date": null,
  "fetched_at": "2026-03-14T17:12:04.288424",
  "created_at": "2026-03-13T22:19:14",
  "company_symbol": "RELIANCE"
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