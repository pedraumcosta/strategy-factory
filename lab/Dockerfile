# freqtrade 2026.8 + statsmodels.
# Strategy005 (the strategy that traded live in Sep 2020) computes its `slope` indicator
# with statsmodels OLS, and `slope` is load-bearing in its entry condition. The official
# image does not ship statsmodels, so reproducing the 2020 backtest faithfully needs this
# layer rather than a substituted implementation. The 2020 setup had the same problem --
# its docker-compose referenced a locally built image named "sujeratrade".
FROM freqtradeorg/freqtrade:stable
USER ftuser
RUN pip install --user --no-cache-dir statsmodels
