-- CreateTable
CREATE TABLE "UserSettings" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "watchlistColumns" TEXT NOT NULL DEFAULT '["ltp","chg","1w","1m","3m","6m","1y"]',
    "moversColumns" TEXT NOT NULL DEFAULT '["close","chg","1w","1m","3m","6m","1y"]',
    "updatedAt" DATETIME NOT NULL
);
