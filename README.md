# Warrant showcases

Working demonstrations of Warrant. Warrant lets an owner approve a payment policy, lets an
agent propose a payment, and lets a contract enforce the decision.

The core is in [`mnemonik-xyz/policy-execution`](https://github.com/mnemonik-xyz/policy-execution).
This repository holds the showcases only. They use the core as a pinned release:
compiled binaries and compiled contracts, not source.

| Showcase | What it is |
|---|---|
| [`showcases/ionet_arc`](showcases/ionet_arc/README.md) | A buyer agent buys a GPU transcription session from an io.net seller. Payment goes through an escrow on Arc. |

## The pinned core

[`core.lock`](core.lock) names one `policy-execution` release (`core-v*`) and the SHA-256
digest of each file in it. It also records the guest image IDs and the code hashes of the
compiled contracts.

```sh
python scripts/fetch_core.py fetch    # download into .core/ and check every digest
python scripts/fetch_core.py verify   # check that .core/ matches core.lock
python scripts/fetch_core.py lock core-v0.1.1   # write core.lock from a published release
```

- `fetch` never trusts the release. It stops when a digest differs from `core.lock`.
- `lock` trusts the release once. Review the `core.lock` diff before you commit it.
- To upgrade the core, run `lock` for the new tag and merge the change by pull request.
- `warrant-host` is published for linux x86_64 only. The other binaries also exist for linux
  arm64 and macOS arm64.

## Tests

```sh
pip install -r showcases/ionet_arc/requirements-dev.txt
python scripts/fetch_core.py fetch
python showcases/ionet_arc/init.py          # test keys and credentials; changes tracked config files
python -m unittest discover tests
python -m unittest discover showcases/ionet_arc
```

`init.py` regenerates test credentials in `showcases/ionet_arc/config`. Do not commit that change.
The end-to-end test needs `anvil` and `IO_NET_API_KEY`. Without them it is skipped.

## License

See [LICENSE](LICENSE).
