import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import ServiceGatewayOperatorsPanel from '@/views/gateway/ServiceGatewayOperatorsPanel.vue'
import type { ServiceGatewayOperatorStatus } from '@/api/serviceGatewayOperator'

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  legacyGateways: vi.fn(),
  status: vi.fn(),
  act: vi.fn(),
}))

vi.mock('@/api/serviceGatewayOperator', () => ({
  serviceGatewayOperatorApi: apiMocks,
}))

const profile = {
  profile_ref: 'account-owner-r1',
  role: 'account_session_worker' as const,
  account_ref: 'account-r1',
  operations: ['status', 'start', 'stop', 'recover'] as Array<'status' | 'start' | 'stop' | 'recover' | 'cleanup'>,
  auto_start: false,
}

const buttonStub = defineComponent({
  props: ['disabled', 'loading', 'nativeType'],
  emits: ['click'],
  setup(props, { emit, slots }) {
    return () => h('button', {
      class: 'el-button',
      disabled: props.disabled || props.loading,
      type: props.nativeType || 'button',
      onClick: (event: MouseEvent) => emit('click', event),
    }, slots.default?.())
  },
})

function mountPanel(attachToDocument = false) {
  return mount(ServiceGatewayOperatorsPanel, {
    global: { stubs: { 'el-button': buttonStub } },
    ...(attachToDocument ? { attachTo: document.body } : {}),
  })
}

function makeStatus(overrides: Record<string, unknown> = {}) {
  return {
    profile_ref: profile.profile_ref,
    account_ref: profile.account_ref,
    role: profile.role,
    state: 'new' as const,
    ready: false,
    error_code: null,
    operation: { name: null, state: 'idle' as const, error_code: null },
    account_session: null,
    cleanup: { unclaimed_provider_count: 0, last_cleanup_code: null },
    ...overrides,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

async function flushUi() {
  await flushPromises()
}

describe('ServiceGatewayOperatorsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.list.mockResolvedValue({ operators: [profile] })
    apiMocks.legacyGateways.mockResolvedValue({ gateways: [] })
    apiMocks.status.mockResolvedValue(makeStatus())
    apiMocks.act.mockResolvedValue(makeStatus({ state: 'running', ready: true }))
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('reads only server-authorized profiles and status on mount; start requires a click', async () => {
    const wrapper = mountPanel(true)
    await flushUi()

    expect(apiMocks.list).toHaveBeenCalledOnce()
    expect(apiMocks.status).toHaveBeenCalledWith(profile.profile_ref)
    expect(apiMocks.act).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('account-owner-r1')
    expect(wrapper.text()).toContain('账户会话 owner')
    expect(wrapper.findAll('button').some((button) => button.text() === '恢复会话')).toBe(false)

    const startButton = wrapper.findAll('button').find((button) => button.text() === '启动服务')
    expect(startButton).toBeDefined()
    await startButton!.trigger('click')
    await flushUi()

    expect(apiMocks.act).toHaveBeenCalledOnce()
    expect(apiMocks.act).toHaveBeenCalledWith(profile.profile_ref, 'start')
    expect(wrapper.text()).toContain('running')
    wrapper.unmount()
  })

  it('shows explicit unavailable state without falling back when the service is not configured', async () => {
    apiMocks.list.mockRejectedValue({
      response: { status: 503, data: { detail: { code: 'OPERATOR_NOT_CONFIGURED' } } },
    })
    const wrapper = mountPanel()
    await flushUi()

    expect(wrapper.get('[data-test="operator-list-error"]').text()).toContain('服务端未配置 Service Gateway operator')
    expect(apiMocks.status).not.toHaveBeenCalled()
    expect(apiMocks.act).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows only exact owner-authorized legacy profile mappings and never starts automatically', async () => {
    apiMocks.legacyGateways.mockResolvedValue({
      gateways: [
        {
          gateway_key: 'manual:OKX:account-1',
          migration_status: 'profile_available',
          profile_ref: 'account-owner-r1',
        },
      ],
    })
    const wrapper = mountPanel()
    await flushUi()

    expect(apiMocks.legacyGateways).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('manual:OKX:account-1')
    expect(wrapper.text()).toContain('account-owner-r1')
    expect(wrapper.text()).toContain('已绑定授权 profile')
    expect(wrapper.text()).toContain('未映射的旧 key 不会在此显示；管理员需要配置 owner 映射')
    expect(wrapper.text()).not.toContain('manual:CTP:unmapped')
    expect(apiMocks.act).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('fails closed on an unexpected legacy projection without hiding authorized operator controls', async () => {
    apiMocks.legacyGateways.mockResolvedValue({
      gateways: [{
        gateway_key: 'manual:OKX:account-1',
        migration_status: 'profile_available',
        profile_ref: 'account-owner-r1',
        credentials: { api_key: 'must-not-render' },
      }],
    })
    const wrapper = mountPanel()
    await flushUi()

    expect(wrapper.find('[data-test="operator-card-account-owner-r1"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="legacy-gateway-error"]').text()).toContain('Service Gateway 状态不可用')
    expect(wrapper.text()).not.toContain('must-not-render')
    expect(apiMocks.status).toHaveBeenCalledWith(profile.profile_ref)
    expect(apiMocks.act).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not offer an operation absent from the server grant', async () => {
    apiMocks.list.mockResolvedValue({
      operators: [{ ...profile, operations: ['status', 'stop'] }],
    })
    const wrapper = mountPanel()
    await flushUi()

    expect(wrapper.findAll('button').some((button) => button.text() === '启动服务')).toBe(false)
    expect(wrapper.findAll('button').some((button) => button.text() === '恢复会话')).toBe(false)
    wrapper.unmount()
  })

  it('rejects a status response that is not bound to the selected server profile', async () => {
    apiMocks.status.mockResolvedValue(makeStatus({ profile_ref: 'other-profile' }))
    const wrapper = mountPanel()
    await flushUi()

    expect(wrapper.find('[data-test="operator-status-error-account-owner-r1"]').text()).toContain('Service Gateway 状态不可用')
    expect(wrapper.findAll('button').some((button) => button.text() === '启动服务')).toBe(false)
    expect(apiMocks.act).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not offer a fresh start when the prior operator result is uncertain', async () => {
    apiMocks.status.mockResolvedValue(makeStatus({
      state: 'failed',
      operation: { name: 'start', state: 'outcome_uncertain', error_code: 'APPLICATION_START_TIMEOUT' },
    }))
    const wrapper = mountPanel()
    await flushUi()

    expect(wrapper.findAll('button').some((button) => button.text() === '启动服务')).toBe(false)
    expect(apiMocks.act).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('refreshes owner status after an uncertain action failure before offering another start', async () => {
    apiMocks.status.mockReset()
      .mockResolvedValueOnce(makeStatus())
      .mockResolvedValueOnce(makeStatus({
        state: 'uncertain',
        operation: { name: 'start', state: 'outcome_uncertain', error_code: 'APPLICATION_START_TIMEOUT' },
      }))
    apiMocks.act.mockRejectedValue({
      response: { status: 503, data: { detail: { code: 'APPLICATION_START_TIMEOUT' } } },
    })
    const wrapper = mountPanel()
    await flushUi()

    const startButton = wrapper.findAll('button').find((button) => button.text() === '启动服务')
    expect(startButton).toBeDefined()
    await startButton!.trigger('click')
    await flushUi()

    expect(apiMocks.act).toHaveBeenCalledWith(profile.profile_ref, 'start')
    expect(apiMocks.status).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('button').some((button) => button.text() === '启动服务')).toBe(false)
    expect(wrapper.text()).toContain('APPLICATION_START_TIMEOUT')
    wrapper.unmount()
  })

  it.each([
    ['running', makeStatus({ state: 'running', ready: true })],
    ['uncertain', makeStatus({
      state: 'uncertain',
      operation: { name: 'start', state: 'outcome_uncertain', error_code: 'APPLICATION_START_TIMEOUT' },
    })],
  ] as Array<[string, ServiceGatewayOperatorStatus]>)('does not let a refresh overwrite a pending start with stale new status (%s)', async (_state, result) => {
    const pendingAction = deferred<ServiceGatewayOperatorStatus>()
    apiMocks.act.mockReturnValue(pendingAction.promise)
    const wrapper = mountPanel(true)
    await flushUi()

    const startButton = wrapper.findAll('button').find((button) => button.text() === '启动服务')
    expect(startButton).toBeDefined()
    await startButton!.trigger('click')
    expect(apiMocks.act).toHaveBeenCalledOnce()

    const refreshButton = wrapper.findAll('button').find((button) => button.text() === '刷新')
    expect(refreshButton).toBeDefined()
    expect(refreshButton!.attributes('disabled')).toBeDefined()
    await refreshButton!.trigger('click')
    expect(apiMocks.list).toHaveBeenCalledOnce()
    expect(apiMocks.status).toHaveBeenCalledOnce()

    pendingAction.resolve(result)
    await flushUi()

    expect(wrapper.text()).toContain(result.state)
    expect(apiMocks.list).toHaveBeenCalledOnce()
    expect(apiMocks.status).toHaveBeenCalledOnce()
    if (result.operation.state === 'outcome_uncertain') {
      expect(wrapper.findAll('button').some((button) => button.text() === '启动服务')).toBe(false)
    }
    wrapper.unmount()
  })

  it('waits for an in-flight refresh before allowing start', async () => {
    const pendingStatus = deferred<ServiceGatewayOperatorStatus>()
    const wrapper = mountPanel()
    await flushUi()
    apiMocks.status.mockReturnValue(pendingStatus.promise)

    const refreshButton = wrapper.findAll('button').find((button) => button.text() === '刷新')
    expect(refreshButton).toBeDefined()
    await refreshButton!.trigger('click')
    await flushUi()

    expect(refreshButton!.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('button').some((button) => button.text() === '启动服务')).toBe(false)
    expect(apiMocks.act).not.toHaveBeenCalled()

    pendingStatus.resolve(makeStatus())
    await flushUi()
    const startButton = wrapper.findAll('button').find((button) => button.text() === '启动服务')
    expect(startButton).toBeDefined()
    await startButton!.trigger('click')
    await flushUi()

    expect(apiMocks.act).toHaveBeenCalledWith(profile.profile_ref, 'start')
    expect(wrapper.text()).toContain('running')
    wrapper.unmount()
  })

  it('displays unavailable cleanup counts as unknown and keeps start blocked', async () => {
    apiMocks.status.mockResolvedValue(makeStatus({
      cleanup: { unclaimed_provider_count: null, last_cleanup_code: null },
    }))
    const wrapper = mountPanel()
    await flushUi()

    expect(wrapper.text()).toContain('待清理 provider')
    expect(wrapper.text()).toContain('未知')
    expect(wrapper.findAll('button').some((button) => button.text() === '启动服务')).toBe(false)
    wrapper.unmount()
  })
})
