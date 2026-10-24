import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Card,
  ConfirmDialog,
  Field,
  Input,
} from "@/components/ui";
import { api } from "@/lib/api";
import { getError, useErrorMessage } from "@/lib/errors";
import type {
  AttendanceRules,
  ScheduleShiftInput,
  ScheduleVersion,
  Scheduling,
  SchedulingWriteResult,
  ShiftCode,
  ShiftsInput,
} from "@/lib/types";
import { invalidateScheduling, useShiftName } from "../api";
import { AppliesFrom, ApplyToAll, useDayName } from "./shared";

interface Form extends AttendanceRules {
  shifts: ScheduleShiftInput[];
}

function toForm(v: ScheduleVersion): Form {
  return {
    open_before_min: v.open_before_min,
    absent_after_min: v.absent_after_min,
    checkout_window_min: v.checkout_window_min,
    reminders_enabled: v.reminders_enabled,
    count_early_checkin: v.count_early_checkin,
    count_overtime: v.count_overtime,
    shifts: v.shifts.map((s) => ({
      code: s.code,
      name_km: s.name_km,
      name_en: s.name_en,
      start_time: s.start_time,
      end_time: s.end_time,
    })),
  };
}

function minutes(hm: string): number | null {
  const m = /^(\d{2}):(\d{2})$/.exec(hm);
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

function hm(total: number): string {
  const day = ((total % 1440) + 1440) % 1440;
  return `${String(Math.floor(day / 60)).padStart(2, "0")}:${String(day % 60).padStart(2, "0")}`;
}

// The API's validation messages for an impossible day (windows.validate) → translation keys.
const PROBLEMS: Record<string, string> = {
  "The shift must end after it starts": "endBeforeStart",
  "Shifts must not overlap": "overlap",
  "The check-in window starts before midnight": "beforeMidnight",
  "The check-out window ends after midnight": "afterMidnight",
  "Check-in must close by the end of the shift": "checkInAfterEnd",
  "Two check-in windows overlap": "checkInOverlap",
  "Two check-out windows overlap": "checkOutOverlap",
};

/** The windows a shift gets from the rules, exactly like the API (closing minute included). */
function preview(start: string, end: string, f: Form) {
  const s = minutes(start);
  const e = minutes(end);
  if (s === null || e === null) return null;
  return {
    checkIn: `${hm(s - f.open_before_min)}–${hm(s + f.absent_after_min - 1)}`,
    late: hm(s),
    absent: hm(s + f.absent_after_min),
    checkOut: `${hm(e)}–${hm(e + f.checkout_window_min)}`,
    forgot: hm(e + f.checkout_window_min + 1),
  };
}

interface ShiftsCardProps {
  /** The page's workplace only (`workplaces[0]`); `workplace_options` are every active one. */
  scheduling: Scheduling;
  /** attendance.scheduling; read-only otherwise. */
  canEdit: boolean;
  onDone(message: string): void;
}

/**
 * Shift schedule and rules: both shifts' times, the window rules, the GPS accuracy limit,
 * reminders and whether early check-ins / overtime count as extra time, with a live preview of
 * each shift's windows. Saved for the page's workplace (or, with "Apply to all workplaces" and a
 * confirmation, every workplace) from "Applies from" in one request (PUT
 * /attendance/scheduling/shifts), validated by the API as a whole day.
 */
export function ShiftsCard({ scheduling, canEdit, onDone }: ShiftsCardProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const errorMessage = useErrorMessage();
  const shiftName = useShiftName();
  const formatDay = useDayName();
  const workplace = scheduling.workplaces[0];
  const first = workplace?.current;
  const others = scheduling.workplace_options.length - 1;
  const today = scheduling.today;
  const [form, setForm] = useState<Form | null>(() =>
    first ? toForm(first) : null,
  );
  const [from, setFrom] = useState(today);
  const [applyAll, setApplyAll] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const key = first?.id;
  useEffect(() => {
    if (first) setForm(toForm(first));
    setFrom(today);
    setApplyAll(false);
    // Reset when the workplace or its current version changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, today]);

  const save = useMutation({
    mutationFn: async (body: ShiftsInput) =>
      (
        await api.put<SchedulingWriteResult>(
          "/attendance/scheduling/shifts",
          body,
        )
      ).data,
    onSuccess: () => {
      invalidateScheduling(queryClient);
      setConfirming(false);
      onDone(t("attendance.scheduling.shifts.saved"));
    },
  });

  if (!form) return null;

  const saveError = (err: unknown): string => {
    const { code, details } = getError(err);
    const fields = (details.fields ?? []) as { msg: string }[];
    const known =
      code === "VALIDATION_ERROR"
        ? fields.map((f) => PROBLEMS[f.msg]).filter(Boolean)
        : [];
    return known.length
      ? [...new Set(known)]
          .map((k) => t(`attendance.shiftsPage.problems.${k}`))
          .join(" ")
      : errorMessage(err);
  };

  const update = (patch: Partial<Form>) => {
    save.reset();
    setForm((f) => (f ? { ...f, ...patch } : f));
  };
  const updateShift = (
    code: ShiftCode,
    patch: { start_time?: string; end_time?: string },
  ) =>
    update({
      shifts: form.shifts.map((s) =>
        s.code === code ? { ...s, ...patch } : s,
      ),
    });

  const body = (): ShiftsInput => ({
    ...form,
    workplace_ids: applyAll ? "all" : [workplace.id],
    effective_from: from,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (applyAll) setConfirming(true);
    else save.mutate(body());
  };

  const number = (
    key: keyof AttendanceRules,
    label: string,
    hint: string,
    min: number,
    max: number,
  ) => (
    <Field label={label} hint={hint}>
      {(id) => (
        <Input
          id={id}
          type="number"
          inputMode="numeric"
          min={min}
          max={max}
          value={String(form[key])}
          disabled={!canEdit}
          onChange={(e) => update({ [key]: Number(e.target.value) })}
        />
      )}
    </Field>
  );

  type Flag = "reminders_enabled" | "count_early_checkin" | "count_overtime";
  const toggle = (key: Flag, label: string, hint?: string) => (
    <label className="flex items-start gap-3 text-sm">
      <input
        type="checkbox"
        className="mt-0.5 h-4 w-4 rounded border-stone-300 text-brand-600 focus:ring-brand-500"
        checked={form[key]}
        disabled={!canEdit}
        onChange={(e) => update({ [key]: e.target.checked })}
      />
      <span>
        <span className="font-medium text-stone-900">{label}</span>
        {hint && <span className="block text-stone-500">{hint}</span>}
      </span>
    </label>
  );

  return (
    <>
      <form onSubmit={submit}>
        <Card title={t("attendance.scheduling.shifts.title")}>
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              {form.shifts.map((s) => {
                const p = preview(s.start_time, s.end_time, form);
                return (
                  <div
                    key={s.code}
                    className="rounded-lg p-3 ring-1 ring-stone-200"
                  >
                    <h3 className="mb-2 text-sm font-semibold text-stone-800">
                      {shiftName(s.code)}
                    </h3>
                    <div className="grid grid-cols-2 gap-3">
                      <Field label={t("attendance.shiftsPage.start")}>
                        {(id) => (
                          <Input
                            id={id}
                            type="time"
                            value={s.start_time}
                            disabled={!canEdit}
                            onChange={(e) =>
                              updateShift(s.code, {
                                start_time: e.target.value,
                              })
                            }
                          />
                        )}
                      </Field>
                      <Field label={t("attendance.shiftsPage.end")}>
                        {(id) => (
                          <Input
                            id={id}
                            type="time"
                            value={s.end_time}
                            disabled={!canEdit}
                            onChange={(e) =>
                              updateShift(s.code, { end_time: e.target.value })
                            }
                          />
                        )}
                      </Field>
                    </div>
                    {p && (
                      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 rounded-lg bg-stone-50 p-3 text-xs">
                        <dt className="text-stone-500">
                          {t("attendance.shiftsPage.checkInWindow")}
                        </dt>
                        <dd className="font-medium tabular-nums">
                          {p.checkIn}
                        </dd>
                        <dt className="text-stone-500">
                          {t("attendance.shiftsPage.lateAfter")}
                        </dt>
                        <dd className="font-medium tabular-nums">{p.late}</dd>
                        <dt className="text-stone-500">
                          {t("attendance.shiftsPage.absentFrom")}
                        </dt>
                        <dd className="font-medium tabular-nums">{p.absent}</dd>
                        <dt className="text-stone-500">
                          {t("attendance.shiftsPage.checkOutWindow")}
                        </dt>
                        <dd className="font-medium tabular-nums">
                          {p.checkOut}
                        </dd>
                        <dt className="text-stone-500">
                          {t("attendance.shiftsPage.forgotFrom")}
                        </dt>
                        <dd className="font-medium tabular-nums">{p.forgot}</dd>
                      </dl>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {number(
                "open_before_min",
                t("attendance.shiftsPage.openBefore"),
                t("attendance.shiftsPage.openBeforeHint"),
                1,
                120,
              )}
              {number(
                "absent_after_min",
                t("attendance.shiftsPage.absentAfter"),
                t("attendance.shiftsPage.absentAfterHint"),
                1,
                240,
              )}
              {number(
                "checkout_window_min",
                t("attendance.shiftsPage.checkoutWindow"),
                t("attendance.shiftsPage.checkoutWindowHint"),
                0,
                180,
              )}
            </div>
            {toggle(
              "reminders_enabled",
              t("attendance.shiftsPage.reminders"),
              t("attendance.shiftsPage.remindersHint"),
            )}
            <div className="space-y-2">
              {toggle(
                "count_early_checkin",
                t("attendance.shiftsPage.countEarly"),
              )}
              {toggle(
                "count_overtime",
                t("attendance.shiftsPage.countOvertime"),
              )}
              <p className="pl-7 text-sm text-stone-500">
                {t("attendance.shiftsPage.extraHint")}
              </p>
            </div>
            {canEdit && (
              <>
                <AppliesFrom value={from} min={today} onChange={setFrom} />
                <Alert tone="info">
                  {t("attendance.shiftsPage.appliesNext")}
                </Alert>
                {save.isError && !confirming && (
                  <Alert tone="error">{saveError(save.error)}</Alert>
                )}
                <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2">
                  <ApplyToAll
                    checked={applyAll}
                    onChange={setApplyAll}
                    others={others}
                  />
                  <Button type="submit" loading={save.isPending && !confirming}>
                    {t("common.save")}
                  </Button>
                </div>
              </>
            )}
          </div>
        </Card>
      </form>
      {confirming && (
        <ConfirmDialog
          open
          title={t("attendance.scheduling.applyAllTitle")}
          body={t("attendance.scheduling.shifts.applyAllConfirm", {
            count: others,
            date: formatDay(from),
          })}
          confirmLabel={t("common.save")}
          loading={save.isPending}
          error={save.isError ? saveError(save.error) : null}
          onConfirm={() => save.mutate(body())}
          onClose={() => {
            setConfirming(false);
            save.reset();
          }}
        />
      )}
    </>
  );
}
