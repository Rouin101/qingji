import test from "node:test";
import assert from "node:assert/strict";
import {
  isTaskOverdue,
  filterAndSortTasks,
  computeTaskCounts,
} from "../src/task-filter-helpers.js";

const fixedToday = "2026-10-04";

test("isTaskOverdue: only open task strictly before today is overdue", () => {
  // Past date, open -> overdue
  assert.equal(
    isTaskOverdue({ status: "open", due_date: "2026-10-03" }, fixedToday),
    true
  );
  // Today, open -> NOT overdue (today is not past)
  assert.equal(
    isTaskOverdue({ status: "open", due_date: "2026-10-04" }, fixedToday),
    false
  );
  // Future date, open -> NOT overdue
  assert.equal(
    isTaskOverdue({ status: "open", due_date: "2026-10-05" }, fixedToday),
    false
  );
  // Past date, but status is done -> NOT overdue
  assert.equal(
    isTaskOverdue({ status: "done", due_date: "2026-10-01" }, fixedToday),
    false
  );
  // No due date -> NOT overdue
  assert.equal(
    isTaskOverdue({ status: "open", due_date: "" }, fixedToday),
    false
  );
});

test("filterAndSortTasks: status filtering defaults to pending excluding done", () => {
  const tasks = [
    { id: "t1", status: "open", due_date: "2026-10-06" },
    { id: "t2", status: "done", due_date: "2026-10-01" },
    { id: "t3", status: "material_added", due_date: "2026-10-05" },
  ];

  const pending = filterAndSortTasks(tasks, { statusFilter: "pending" });
  assert.equal(pending.length, 2);
  assert.deepEqual(
    pending.map((t) => t.id),
    ["t3", "t1"] // t3 (10-05) before t1 (10-06)
  );

  const done = filterAndSortTasks(tasks, { statusFilter: "done" });
  assert.equal(done.length, 1);
  assert.equal(done[0].id, "t2");

  const all = filterAndSortTasks(tasks, { statusFilter: "all" });
  assert.equal(all.length, 3);
});

test("filterAndSortTasks: sorts chronological ascending, no dates last, preserves tie order", () => {
  const tasks = [
    { id: "no-date-1", status: "open", due_date: "" },
    { id: "date-later", status: "open", due_date: "2026-10-10" },
    { id: "date-earlier-a", status: "open", due_date: "2026-10-02" },
    { id: "date-earlier-b", status: "open", due_date: "2026-10-02" },
    { id: "no-date-2", status: "open", due_date: "" },
  ];

  const sorted = filterAndSortTasks(tasks, { statusFilter: "all" });
  assert.deepEqual(
    sorted.map((t) => t.id),
    ["date-earlier-a", "date-earlier-b", "date-later", "no-date-1", "no-date-2"]
  );
});

test("filterAndSortTasks: assignee and kind filters", () => {
  const tasks = [
    { id: "t1", status: "open", assignee_id: "u1", kind: "evidence" },
    { id: "t2", status: "open", assignee_id: "", kind: "practice" },
    { id: "t3", status: "open", assignee_id: "u2", kind: "evidence" },
  ];

  const forU1 = filterAndSortTasks(tasks, {
    statusFilter: "all",
    assigneeFilter: "u1",
  });
  assert.equal(forU1.length, 1);
  assert.equal(forU1[0].id, "t1");

  const unassigned = filterAndSortTasks(tasks, {
    statusFilter: "all",
    assigneeFilter: "unassigned",
  });
  assert.equal(unassigned.length, 1);
  assert.equal(unassigned[0].id, "t2");

  const practices = filterAndSortTasks(tasks, {
    statusFilter: "all",
    kindFilter: "practice",
  });
  assert.equal(practices.length, 1);
  assert.equal(practices[0].id, "t2");
});

test("computeTaskCounts: accurate pending, done, all, and overdue counts", () => {
  const tasks = [
    { id: "t1", status: "open", due_date: "2026-10-03" }, // overdue
    { id: "t2", status: "open", due_date: "2026-10-04" }, // today (not overdue)
    { id: "t3", status: "open", due_date: "2026-10-05" }, // future (not overdue)
    { id: "t4", status: "done", due_date: "2026-10-01" }, // done (not overdue)
    { id: "t5", status: "open", due_date: "" },           // no date (not overdue)
  ];

  const counts = computeTaskCounts(tasks, fixedToday);
  assert.equal(counts.all, 5);
  assert.equal(counts.pending, 4);
  assert.equal(counts.done, 1);
  assert.equal(counts.overdue, 1);
});
