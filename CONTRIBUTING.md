# Contributing

Issues and pull requests are welcome.

- **Service availability.** The catalog lives in `src/sovlens/data/esc_services.json` and follows the AWS European Sovereign Cloud User Guide. A change needs a link to a public AWS source. Use the "Service availability correction" issue template if you are not sure how to change the file.
- **Code.** Keep the scanner read-only: it must never call an API that creates, changes or deletes anything. Add a test with [moto](https://github.com/getmoto/moto) for new checks.

```sh
pip install -e ".[dev]"
pytest
```
