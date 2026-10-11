"use client";

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAtomValue } from "jotai";
import { advancedScrapingConsentAtom } from "@/store/terminalStore";
import { openLink, isExternalClick } from "@/lib/openLink";
import type { NewsArticle } from "@/lib/newsSocket";

const PAGE_LIMIT = 50;

type NewsSource = "auto" | "iinvest" | "moneycontrol" | "merged";

interface NewsPaginatedResponse {
  articles: NewsArticle[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  source_used?: string | null;
}

export function CompanyNewsTab({ symbol }: { symbol: string }) {
  const scrapingConsent = useAtomValue(advancedScrapingConsentAtom);
  const [offset, setOffset] = useState(0);
  const [source, setSource] = useState<NewsSource>("merged");

  const effectiveSource =
    scrapingConsent === false && (source === "iinvest" || source === "auto")
      ? "moneycontrol"
      : source;

  const { data, isLoading, error } = useQuery<NewsPaginatedResponse>({
    queryKey: ["news/company", symbol, { limit: PAGE_LIMIT, offset, source: effectiveSource }],
    queryFn: async () => {
      const res = await fetch(
        `/api/py/news/company/${encodeURIComponent(symbol)}?limit=${PAGE_LIMIT}&offset=${offset}&source=${effectiveSource}`
      );
      if (res.status === 404) {
        const postRes = await fetch("/api/py/news/company", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol }),
        });
        if (!postRes.ok) throw new Error("Failed to fetch company news");
        return postRes.json();
      }
      if (!res.ok) throw new Error("Failed to fetch company news");
      return res.json();
    },
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  });

  if (isLoading) {
    return (
      <div className="h-full w-full flex items-center justify-center font-mono text-sm text-terminal-amber animate-pulse">
        LOADING NEWS...
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full w-full flex items-center justify-center font-mono text-sm text-terminal-red">
        FAILED TO LOAD NEWS
      </div>
    );
  }

  const articles = data?.articles || [];

  return (
    <div className="h-full w-full flex flex-col font-mono text-sm bg-terminal-bg">
      {/* Controls */}
      <div className="flex items-center gap-2 px-2 py-2 border-b border-terminal-gray/30 bg-terminal-gray/10">
        <select
          value={source}
          onChange={(e) => {
            setSource(e.target.value as NewsSource);
            setOffset(0);
          }}
          className="bg-[#111] text-terminal-amber border border-terminal-gray/50 rounded px-2 py-1 outline-none focus:border-terminal-amber transition-colors"
        >
          <option value="merged">Merged</option>
          <option value="moneycontrol">MoneyControl</option>
          <option value="iinvest">iInvest</option>
        </select>
        <div className="text-white/60 text-xs ml-auto">
          {articles.length} articles
        </div>
      </div>

      {/* Articles */}
      <div className="flex-1 overflow-y-auto p-2 space-y-4">
        {articles.length === 0 ? (
          <div className="text-white/60 text-center py-4">No company news found</div>
        ) : (
          articles.map((article, i) => (
            <div
              key={`${article.url}-${i}`}
              className="group border border-terminal-gray/30 rounded p-2 hover:bg-terminal-gray/10 transition-colors duration-300 ease-out cursor-pointer"
              onClick={(e) => {
                if (article.url) openLink(article.url, isExternalClick(e) ? "external" : "app");
              }}
            >
              <div className="flex items-center gap-2 mb-1 text-xs">
                <span className="text-terminal-amber/80 uppercase">{article.source}</span>
                <span className="text-white/40">•</span>
                <span className="text-white/40">{new Date(article.publish_date || "").toLocaleString()}</span>
              </div>
              <h3 className="text-white text-sm font-semibold leading-relaxed group-hover:text-terminal-amber transition-colors">
                {article.title}
              </h3>
              {article.text && (
                <p className="mt-1 text-white/70 text-xs leading-relaxed line-clamp-2">
                  {article.text}
                </p>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
