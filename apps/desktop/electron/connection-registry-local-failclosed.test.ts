/**
 * Local patch: fail-closed "This device" while global remote mode is active.
 * A forced-local dial runs `gateway ensure` from the desktop's own install and,
 * when that Hermes differs from the remote fleet on the same host, spawns a
 * detached duplicate gateway. Without an explicit opt-in it must be refused.
 */
import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  LOCAL_CONNECTION_ID,
  LOCAL_DISABLED_WHILE_REMOTE,
  localSpawnRefusal,
  localWithRemoteAllowed,
  resolveRegistryLocalRoute,
  shouldDeferLocalEnumeration,
  visibleRegistryConnections
} from './connection-registry'

test('fail-closed: global remote without opt-in refuses every forced-local route', () => {
  for (const profile of ['default', 'angel', 'research', '', null]) {
    const route = resolveRegistryLocalRoute(profile, { globalRemote: true, localProfileExists: true })

    assert.equal(route.delegate, false, `delegate for ${String(profile)}`)
    assert.equal(route.refuse, LOCAL_DISABLED_WHILE_REMOTE, `refuse for ${String(profile)}`)
    assert.ok(route.poolKey.startsWith(`conn:${LOCAL_CONNECTION_ID}::`))
  }
})

test('fail-closed: explicit opt-in restores the upstream forced-local behavior', () => {
  const route = resolveRegistryLocalRoute('angel', {
    allowLocalWithRemote: true,
    globalRemote: true,
    localProfileExists: true
  })

  assert.deepEqual(route, { delegate: false, poolKey: 'conn:local::angel' })
})

test('fail-closed: local mode and per-profile overrides are unchanged', () => {
  assert.deepEqual(resolveRegistryLocalRoute('angel', {}), { delegate: true, poolKey: 'angel' })
  assert.deepEqual(resolveRegistryLocalRoute('angel', { globalRemote: false }), { delegate: true, poolKey: 'angel' })
  assert.deepEqual(resolveRegistryLocalRoute('angel', { globalRemote: true, profileRemoteOverride: true }), {
    delegate: true,
    poolKey: 'angel'
  })
})

test('fail-closed: a refused route is never enumerated as a dial', () => {
  const route = resolveRegistryLocalRoute('default', { globalRemote: true })

  assert.equal(route.refuse, LOCAL_DISABLED_WHILE_REMOTE)
  assert.equal(shouldDeferLocalEnumeration(route, []), true)
})

test('localWithRemoteAllowed: only explicit truthy values opt in', () => {
  assert.equal(localWithRemoteAllowed({}), false)
  assert.equal(localWithRemoteAllowed({ HERMES_DESKTOP_ALLOW_LOCAL_WITH_REMOTE: '' }), false)
  assert.equal(localWithRemoteAllowed({ HERMES_DESKTOP_ALLOW_LOCAL_WITH_REMOTE: '0' }), false)
  assert.equal(localWithRemoteAllowed({ HERMES_DESKTOP_ALLOW_LOCAL_WITH_REMOTE: 'false' }), false)
  assert.equal(localWithRemoteAllowed({ HERMES_DESKTOP_ALLOW_LOCAL_WITH_REMOTE: 'nope' }), false)
  assert.equal(localWithRemoteAllowed({ HERMES_DESKTOP_ALLOW_LOCAL_WITH_REMOTE: '1' }), true)
  assert.equal(localWithRemoteAllowed({ HERMES_DESKTOP_ALLOW_LOCAL_WITH_REMOTE: ' TRUE ' }), true)
  assert.equal(localWithRemoteAllowed({ HERMES_DESKTOP_ALLOW_LOCAL_WITH_REMOTE: 'yes' }), true)
})

test('localSpawnRefusal: last-line guard for local spawn and restart', () => {
  assert.equal(localSpawnRefusal({ globalRemote: true }), LOCAL_DISABLED_WHILE_REMOTE)
  assert.equal(localSpawnRefusal({ globalRemote: true, allowLocalWithRemote: false }), LOCAL_DISABLED_WHILE_REMOTE)
  assert.equal(localSpawnRefusal({ globalRemote: true, allowLocalWithRemote: true }), null)
  assert.equal(localSpawnRefusal({ globalRemote: false }), null)
  assert.equal(localSpawnRefusal({}), null)
})

test('visibleRegistryConnections: hides This device only while refused and not primary', () => {
  const local = { id: LOCAL_CONNECTION_ID, kind: 'local', label: 'This device' }
  const fleet = { id: 'mac-mini-fleet', kind: 'remote', label: 'Mac mini vloot' }

  assert.deepEqual(visibleRegistryConnections([local, fleet], { localRefused: true, primary: fleet.id }), [fleet])
  assert.deepEqual(visibleRegistryConnections([local, fleet], { localRefused: false, primary: fleet.id }), [
    local,
    fleet
  ])
  // Never strand a desktop whose primary is still the local entry.
  assert.deepEqual(visibleRegistryConnections([local, fleet], { localRefused: true, primary: LOCAL_CONNECTION_ID }), [
    local,
    fleet
  ])
})
