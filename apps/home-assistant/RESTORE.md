# Home Assistant `/config` restore

VolSync backs up the `home-assistant-config` PVC nightly at 03:30 UTC to
`s3:https://rustfs.core.stplabs.io/volsync-home-assistant/<cluster>` (restic; key in
`clusters/<cluster>/secrets/home-assistant-volsync-secret.yaml`, password also in the password manager).

The recorder database is not in this backup; it is CNPG/barman (`cnpg-home-assistant` bucket).

## Full restore into the live PVC

HA is down from step 2 to step 5. Set `CTX` to `staging` or `production`.

1. Stop Flux from reconciling the release:
   ```sh
   flux --context $CTX -n home-assistant suspend helmrelease home-assistant
   ```
2. Stop HA so the volume is not in use:
   ```sh
   kubectl --context $CTX -n home-assistant scale deploy home-assistant --replicas=0
   kubectl --context $CTX -n home-assistant wait --for=delete pod -l app.kubernetes.io/name=home-assistant --timeout=120s
   ```
   Optional, so the restore can be undone: back up the current state first. Skip this if the volume is corrupt.
   ```sh
   kubectl --context $CTX -n home-assistant patch replicationsource home-assistant-config --type=merge \
     -p '{"spec":{"trigger":{"manual":"pre-restore"}}}'
   kubectl --context $CTX -n home-assistant wait replicationsource home-assistant-config \
     --for=jsonpath='{.status.lastManualSync}'=pre-restore --timeout=600s
   kubectl --context $CTX -n home-assistant patch replicationsource home-assistant-config --type=json \
     -p '[{"op":"remove","path":"/spec/trigger/manual"}]'
   ```
   The backup you want is now `previous: 1` in step 3, not `0`.
3. Restore. Pick the backup with `previous` (0 = latest, 1 = the one before) or replace it with
   `restoreAsOf: "2026-10-26T12:00:00Z"`:
   ```sh
   kubectl --context $CTX apply -f - <<'EOF'
   apiVersion: volsync.backube/v1alpha1
   kind: ReplicationDestination
   metadata:
     name: home-assistant-restore
     namespace: home-assistant
   spec:
     trigger:
       manual: restore-1
     restic:
       repository: home-assistant-volsync-secret
       destinationPVC: home-assistant-config
       copyMethod: Direct
       previous: 0
       enableFileDeletion: true
       cacheCapacity: 1Gi
       storageClassName: ceph-block
       moverSecurityContext:
         runAsUser: 0
         runAsGroup: 0
   EOF
   ```
   Do not add `fsGroup`: it rewrites file permissions on the volume.
4. Wait for it and check the result:
   ```sh
   kubectl --context $CTX -n home-assistant wait replicationdestination home-assistant-restore \
     --for=jsonpath='{.status.lastManualSync}'=restore-1 --timeout=600s
   kubectl --context $CTX -n home-assistant get replicationdestination home-assistant-restore \
     -o jsonpath='{.status.latestMoverStatus.result}{"\n"}{.status.latestMoverStatus.logs}'
   ```
5. Clean up and start HA:
   ```sh
   kubectl --context $CTX -n home-assistant delete replicationdestination home-assistant-restore
   kubectl --context $CTX -n home-assistant scale deploy home-assistant --replicas=1
   flux --context $CTX -n home-assistant resume helmrelease home-assistant
   ```

## Recovering single files

Restore into a scratch PVC instead of the live one: create a 1Gi `ceph-block` PVC
(for example `ha-restore-scratch`), use it as `destinationPVC` above, and leave out `enableFileDeletion`.
HA keeps running. Mount the scratch PVC in a temporary pod, copy out what you need, then delete
the ReplicationDestination and the PVC.

## Listing backups

```sh
kubectl --context $CTX -n home-assistant run restic-ls --rm -i --restart=Never \
  --image=quay.io/backube/volsync:0.16.0@sha256:0d03a6aad57569eba2c0eaa0848cf4a908d9744b372ff2224bb291a320f36d76 \
  --overrides='{"spec":{"containers":[{"name":"restic-ls","image":"quay.io/backube/volsync:0.16.0@sha256:0d03a6aad57569eba2c0eaa0848cf4a908d9744b372ff2224bb291a320f36d76","envFrom":[{"secretRef":{"name":"home-assistant-volsync-secret"}}],"env":[{"name":"RESTIC_CACHE_DIR","value":"/tmp/c"}],"command":["restic","snapshots"]}]}}'
```
