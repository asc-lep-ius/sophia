import type { ActionResult, SubmitFunction } from "@sveltejs/kit";

/**
 * Keep an enhanced form to one submission in flight, and make the last one
 * carry the last change.
 *
 * Two quick clicks would otherwise be two PATCHes racing to the API, and the
 * one that lands second wins whether or not it was the second click. A change
 * made while a save is in flight is not sent then: the save in flight finishes,
 * and the form is submitted once more with whatever it holds at that moment.
 * Any number of changes during one save collapse into that single follow-up,
 * and only the result of the last save in a chain reaches `settle`. A save
 * counts as in flight until `settle` returns, so a change made while the page
 * is reloading its data waits for that too.
 */
export function serialiseSubmissions(
  settle: (result: ActionResult) => Promise<void> | void,
): SubmitFunction {
  let inFlight = false;
  let resubmit: HTMLFormElement | null = null;

  return ({ cancel, formElement }) => {
    if (inFlight) {
      resubmit = formElement;
      cancel();
      return;
    }
    inFlight = true;

    return async ({ result }) => {
      try {
        if (!resubmit) {
          await settle(result);
        }
      } finally {
        inFlight = false;
        const next = resubmit;
        resubmit = null;
        next?.requestSubmit();
      }
    };
  };
}
