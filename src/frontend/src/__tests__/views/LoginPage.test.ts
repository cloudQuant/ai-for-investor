import { beforeEach, describe, it, expect, vi } from 'vitest'
import LoginPage from '@/views/LoginPage.vue'
import { mountWithPlugins } from '../mountWithPlugins'

type LoginPageVm = {
  form: { username: string; password: string }
  loading: boolean
}

const authStoreMock = vi.hoisted(() => ({
  login: vi.fn(),
  fetchUser: vi.fn(),
  token: null as string | null,
  identityStatus: 'anonymous' as string,
  identityError: null as string | null,
  isAuthenticated: false,
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => authStoreMock,
}))

vi.mock('vue-i18n', () => ({
  createI18n: vi.fn(() => ({ global: { t: (key: string) => key } })),
  useI18n: vi.fn(() => ({ t: (key: string) => key })),
}))

describe('LoginPage', () => {
  const doMount = () => mountWithPlugins(LoginPage, {
    customStubs: {
      ThemeSwitcher: { template: '<button type="button">theme</button>' },
      LanguageSwitcher: { template: '<button type="button">language</button>' },
    },
  })

  beforeEach(() => {
    vi.clearAllMocks()
    authStoreMock.login.mockReset()
    authStoreMock.fetchUser.mockReset()
    authStoreMock.token = null
    authStoreMock.identityStatus = 'anonymous'
    authStoreMock.identityError = null
    authStoreMock.isAuthenticated = false
  })

  it('renders login form', () => {
    const wrapper = doMount()
    expect(wrapper.text()).toContain('ai-for-investor')
    // i18n mock returns keys
    expect(wrapper.text()).toContain('auth.loginTitle')
    expect(wrapper.text()).toContain('auth.login')
    expect(wrapper.text()).toContain('auth.registerNow')
  })

  it('has reactive form data', () => {
    const wrapper = doMount()
    const vm = wrapper.vm as unknown as LoginPageVm
    expect(vm.form.username).toBe('')
    expect(vm.form.password).toBe('')
    expect(vm.loading).toBe(false)
  })

  it('offers identity retry without allowing another login while identity is unconfirmed', async () => {
    authStoreMock.token = 'retained-token'
    authStoreMock.identityStatus = 'retryable_error'
    authStoreMock.identityError = 'Request failed with status code 503'
    authStoreMock.fetchUser.mockResolvedValue(true)

    const wrapper = doMount()

    expect(wrapper.find('[data-testid="identity-retry-panel"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('auth.identityUnconfirmed')
    expect(wrapper.find('[data-testid="login-submit"]').exists()).toBe(false)

    await wrapper.get('button.el-button').trigger('click')

    expect(authStoreMock.fetchUser).toHaveBeenCalledOnce()
    expect(authStoreMock.login).not.toHaveBeenCalled()
  })

  it('keeps the retry state visible when identity confirmation fails again', async () => {
    authStoreMock.token = 'retained-token'
    authStoreMock.identityStatus = 'retryable_error'
    authStoreMock.identityError = 'Network unavailable'
    authStoreMock.fetchUser.mockResolvedValue(false)

    const wrapper = doMount()
    await wrapper.get('button.el-button').trigger('click')

    expect(authStoreMock.token).toBe('retained-token')
    expect(authStoreMock.login).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="identity-retry-panel"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Network unavailable')
  })
})
