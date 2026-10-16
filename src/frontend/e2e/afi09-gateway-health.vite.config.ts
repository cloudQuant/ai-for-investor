import baseConfig from '../vite.config'

const envDir = process.env.AFI09_E2E_ENV_DIR
if (!envDir) throw new Error('AFI09_E2E_ENV_DIR is required')

// The browser integration uses a fresh, empty directory so Vite cannot load
// any developer .env file while serving the real frontend source.
export default { ...baseConfig, envDir }
