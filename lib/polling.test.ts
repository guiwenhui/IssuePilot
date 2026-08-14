import assert from "node:assert/strict";
import test from "node:test";

import {
  POLL_INTERVAL_MS,
  schedulePoll,
  shouldContinueTaskPolling,
  shouldRetryPoll,
} from "./polling.ts";


test("schedulePoll waits for the documented interval", () => {
  const callback = () => undefined;
  let scheduledCallback: (() => void) | undefined;
  let scheduledDelay: number | undefined;

  const handle = schedulePoll(callback, (next, delay) => {
    scheduledCallback = next;
    scheduledDelay = delay;
    return 42;
  });

  assert.equal(handle, 42);
  assert.equal(scheduledCallback, callback);
  assert.equal(scheduledDelay, POLL_INTERVAL_MS);
});


test("polling retries network and server failures only", () => {
  assert.equal(shouldRetryPoll(), true);
  assert.equal(shouldRetryPoll(503), true);
  assert.equal(shouldRetryPoll(404), false);
  assert.equal(shouldRetryPoll(422), false);
});


test("task polling stops at M2 business terminal states", () => {
  assert.equal(shouldContinueTaskPolling("created"), true);
  assert.equal(shouldContinueTaskPolling("queued"), true);
  assert.equal(shouldContinueTaskPolling("cloning"), true);
  assert.equal(shouldContinueTaskPolling("cloned"), false);
  assert.equal(shouldContinueTaskPolling("failed"), false);
});
