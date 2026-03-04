-- CreateTable
CREATE TABLE "WatchlistItem" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "symbol" TEXT NOT NULL,
    "exchange" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "TopMoverSymbol" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "symbol" TEXT NOT NULL,
    "exchange" TEXT NOT NULL
);

-- CreateIndex
CREATE UNIQUE INDEX "WatchlistItem_symbol_exchange_key" ON "WatchlistItem"("symbol", "exchange");

-- CreateIndex
CREATE UNIQUE INDEX "TopMoverSymbol_symbol_exchange_key" ON "TopMoverSymbol"("symbol", "exchange");
