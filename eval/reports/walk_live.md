# S11 live walks (2026-11-19 07:23 UTC)

Real model on the `agent` alias; scripted store, approver and L2 (mock values).

## CP11.1 printer to fixed: PASS
- ticket LOCAL-LIVE-PO-BC4D32, route resolver, status resolved, reason -; LLM calls 9, tokens 88818, cost $0.0084
- version covered, connection usb, tried []
- steps: po-physical-check (store: replied), po-restart-pos-app (store: replied), po-usb-recognition (action: no_change), po-usb-device-manager (action: no_change), po-usb-spooler-check (approval: done), po-usb-spooler-check (action: fixed)
- end: The latest action result reports the printer status online.

## CP11.4 steps already tried: PASS
- ticket LOCAL-LIVE-TRIED-BC4D32, route resolver, status resolved, reason -; LLM calls 8, tokens 81826, cost $0.0062
- version covered, connection usb, tried ['po-restart-pos-app', 'po-self-test']
- steps: po-physical-check (store: replied), po-usb-recognition (action: no_change), po-usb-device-manager (action: no_change), po-usb-spooler-check (action: fixed)
- end: The latest action result reports the printer status online after restarting the Print Spooler.

## CP11.5 version not covered: PASS
- ticket LOCAL-LIVE-ORBIT-BC4D32, route resolver, status escalated, reason version_not_covered; LLM calls 9, tokens 72525, cost $0.0053
- version not_covered, connection None, tried []
- steps: psf-wait (store: replied), psf-notifications (store: replied), psf-graceful-restart (store: replied)
- end: The asset is OrbitPOS Terminal 1, OrbitPOS v2.1, which is not listed in Affected Systems. Only generic steps may be used, and no remaining approved generic step is available.
