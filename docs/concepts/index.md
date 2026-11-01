# Concepts

This page is the vocabulary of isitright in the order you will meet it, with one example carried
through. Each entry is short and links to the page that explains it in full. If you have not run
anything yet, read this first and then the [quick starts](../get-started/index.md).

## The running example

A retail support agent gets this task:

> *"Hi, I'm Maria Lopez, ZIP 10027. Please cancel my most recent order, I ordered it by mistake, and
> refund me."*

Its policy: identify exactly one customer by name and ZIP, cancel only `pending` orders, refund in
full to the original payment method exactly once, act only on that customer, and do both or neither.
The agent has tools `find_customer`, `list_orders`, `get_order`, `cancel_order` and `refund`. In your
eval world, Maria has three orders, the newest is `pending`, and the agent handles it correctly.

## The ten ideas

| # | Concept | In one sentence | In the example |
|---|---|---|---|
| 1 | [World, state, atoms](worlds-and-mutations.md#world-state-atoms) | The world is everything the agent can observe; a *state* is one concrete version of it; *atoms* are its smallest changeable pieces | The shop's customers, orders, payments and refunds. One order is an atom |
| 2 | [Entity model](worlds-and-mutations.md#the-entity-model) | Worlds are described as collections of typed records with keys and references | `customers`, `orders` (each pointing at a customer), `payments` (each pointing at an order) |
| 3 | [Constraints and validity](validity-and-fidelity.md) | Rules that say which states are allowed, and a label for how many of them a state passed | "Payments sum to the order total" |
| 4 | [Mutations](worlds-and-mutations.md#mutations) | A small, described change from one world to another | A second customer named Maria Lopez in ZIP 10027 |
| 5 | [Subjects](subjects.md) | The thing being tested: a generated query, or a live agent | Your support agent |
| 6 | [Hints](hints.md) | Facts from the task that point the search at what matters | "Most recent" means order by `created_at`, newest first |
| 7 | [Hosts and fidelity](validity-and-fidelity.md#execution-fidelity) | What runs the changed world, and how faithful it is to the real thing | A simulated shop service speaking MCP |
| 8 | [Oracles and roles](oracles-and-roles.md) | A reference that recomputes what is right in each changed world | A reference procedure that follows the policy; *control* worlds where it cancels, *trap* worlds where it does nothing |
| 9 | [Search, budgets, stochastic subjects](live-agents.md) | Generate worlds, run them, stop at a budget; for live agents, repeat runs and compare with a baseline | Run the agent 4 times on the original world, then on the most promising changed worlds |
| 10 | [Minimization, replay, evidence](minimization-and-replay.md) | Shrink a finding to its smallest form, make it reproducible, report it with its strength | "With a second Maria Lopez in the same ZIP, the agent cancelled an order in 6 of 8 runs" (illustrative numbers) |

## One finding, end to end

1. **Generate.** The `key_collision` family reads your `lookup` hint (name and ZIP) and proposes: add
   a second customer who matches it. The world is checked against the schema and your rules (for
   example, payments sum to order totals) and passes as `DOMAIN_VALIDATED`.
2. **Run.** The simulated shop is loaded with this state. Your agent runs against it several times.
   The reference procedure runs against it too, and says: *with two matching customers, make no
   changes* (a *trap* world).
3. **Compare.** The agent cancelled an order. The oracle says that was not allowed. The runs are
   counted against the unchanged world, where the agent behaved correctly.
4. **Minimize.** The mutation path has one step; nothing more to remove.
5. **Report.** `COUNTEREXAMPLE_FOUND`, with the world diff (one added customer), the trace of each run,
   `NATIVE_ISOLATED` or `SIMULATED` fidelity, and a command to replay it offline. Export it, and it
   becomes a new eval case.
6. **You decide.** The policy says to make no changes when it cannot identify exactly one customer,
   so the agent is wrong here. If the policy were silent, this would instead be a finding about the
   policy. isitright never decides that for you.

## Two terms to keep straight

**Counterexample versus evidence.** A *counterexample* is the world where subject and oracle disagree.
*Evidence* is the counterexample plus everything that says how far to trust it: validity, fidelity,
oracle, run counts. [Evidence](evidence.md) explains each field.

**Not found versus correct.** isitright searches within a budget. Finding nothing means nothing was
found in what it tried. It is never a claim that the agent is right.
