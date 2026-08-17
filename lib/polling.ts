export const POLL_INTERVAL_MS = 3_000;

export type PollHandle = number | ReturnType<typeof setTimeout>;
type Scheduler = (callback: () => void, delay: number) => PollHandle;

export function schedulePoll(
  callback: () => void,
  scheduler: Scheduler = setTimeout,
): PollHandle {
  return scheduler(callback, POLL_INTERVAL_MS);
}

export function shouldRetryPoll(status?: number): boolean {
  return status === undefined || status >= 500;
}

export function shouldContinueTaskPolling(status: string): boolean {
  return ![
    "cloned",
    "indexed",
    "retrieved",
    "waiting_approval",
    "failed",
  ].includes(status);
}
