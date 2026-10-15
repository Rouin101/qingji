import { IconChevronLeft, IconChevronRight, IconFilter } from "@tabler/icons-react";

export function ReviewToolbar({
  totalCount = 0,
  pendingCount = 0,
  filter = "all",
  onFilterChange,
  visibleCount = 0,
  currentIndex = -1,
  onPrev,
  onNext,
  disabled = false,
}) {
  const isSpecificStatus = !["all", "pending"].includes(filter);

  return (
    <div className="review-toolbar" role="toolbar" aria-label="结论筛选与逐条导航">
      <div className="review-toolbar-filters">
        <button
          type="button"
          className={`toolbar-filter-btn ${filter === "all" ? "active" : ""}`}
          onClick={() => onFilterChange("all")}
          aria-pressed={filter === "all"}
          disabled={disabled}
        >
          全部 <span className="toolbar-count">{totalCount}</span>
        </button>
        <button
          type="button"
          className={`toolbar-filter-btn ${filter === "pending" ? "active" : ""}`}
          onClick={() => onFilterChange("pending")}
          aria-pressed={filter === "pending"}
          disabled={disabled}
          title="仅显示需要作者取舍且尚未处理的结论"
        >
          待处理 <span className="toolbar-count">{pendingCount}</span>
        </button>

        <label className="toolbar-status-select-wrap">
          <span className="sr-only">按支持程度筛选结论</span>
          <select
            className={`toolbar-status-select ${isSpecificStatus ? "active" : ""}`}
            value={isSpecificStatus ? filter : ""}
            onChange={(e) => onFilterChange(e.target.value || "all")}
            disabled={disabled}
            aria-label="按支持程度筛选"
          >
            <option value="">更多筛选…</option>
            <option value="supported">有对应依据</option>
            <option value="partial">支持较窄</option>
            <option value="unsupported">依据不足</option>
            <option value="disagreement">不同情况与观点</option>
            <option value="pending_verify">待核对</option>
          </select>
        </label>

        {filter !== "all" && (
          <button
            type="button"
            className="text-button toolbar-reset-btn"
            onClick={() => onFilterChange("all")}
            disabled={disabled}
          >
            显示全部
          </button>
        )}
      </div>

      <div className="review-toolbar-nav">
        <span className="toolbar-nav-pos" aria-live="polite">
          {visibleCount === 0
            ? "0 / 0"
            : currentIndex >= 0
            ? `${currentIndex + 1} / ${visibleCount}`
            : `-- / ${visibleCount}`}
        </span>
        <button
          type="button"
          className="toolbar-nav-btn"
          onClick={onPrev}
          disabled={disabled || currentIndex <= 0 || visibleCount === 0}
          aria-label="上一条结论"
          title="上一条结论"
        >
          <IconChevronLeft size={16} aria-hidden="true" />
          <span>上一条</span>
        </button>
        <button
          type="button"
          className="toolbar-nav-btn"
          onClick={onNext}
          disabled={disabled || currentIndex >= visibleCount - 1 || visibleCount === 0}
          aria-label="下一条结论"
          title="下一条结论"
        >
          <span>下一条</span>
          <IconChevronRight size={16} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
