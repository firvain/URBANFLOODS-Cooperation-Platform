import { afterEach, describe, expect, it } from 'vitest'

import RegisterSuccess from '@/components/auth/RegisterSuccess.vue'
import { VERIFICATION_SENDER } from '@/constants/links'
import i18n from '@/i18n'
import { mockApi } from './helpers/api'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

afterEach(unmountAll)

describe('RegisterSuccess', () => {
  it('names the address, the sending address and the spam folder', async () => {
    mockApi({})
    const { wrapper } = await mountWithApp(RegisterSuccess, {
      props: { email: 'new@example.org' },
    })

    expect(VERIFICATION_SENDER).toBe('noreply@cooperation.urbanfloods.app')
    const text = wrapper.text()
    expect(text).toContain('new@example.org')
    expect(text).toContain(VERIFICATION_SENDER)
    expect(text).toContain(t('auth.registerSuccess.noEmail', { sender: VERIFICATION_SENDER }))
    expect(text).toContain('Spam or Junk folder')
  })
})
