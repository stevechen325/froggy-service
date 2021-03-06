<template>
  <div>
    <slot>
      <p>You're not supposed to render this component empty.</p>
    </slot>
  </div>
</template>
<script>

/**
 * @see https://developers.facebook.com/docs/accountkit/webjs
 * to know how to use this
 */
export default {
  name: 'AccountKit',
  data () {
    return {
      appId: '',
      version: '',
      state: 'somecsrf',
      fbAppEventsEnabled: true,
      loginType: 'PHONE',
      language: 'zh_TW',
      autoInit: true,
      display: 'modal'
    }
  },
  created () {
    this.display = this.$store.state.browser === 'ie' ? 'popup' : 'modal'
  },
  props: {
    redirect: {
      type: String,
      default: ''
    }
  },
  mounted () {
    if (!window.AccountKit && this.autoInit) {
      this.appId = process.env.VUE_APP_ACCOUNTKIT_APP_ID
      this.version = process.env.VUE_APP_ACCOUNTKIT_VERSION

      this.getCSRFToken().then(data => {
        this.state = data
        this.initAccountKit()
      })
    }
  },

  methods: {
    getCSRFToken () {
      return this.axios.get('api/csrftoken/')
        .then(response => {
          return response.data['state']
        })
        .catch(e => { console.log(e) })
    },
    initAccountKit () {
      const tag = document.createElement('script')
      tag.setAttribute(
        'src',
        `https://sdk.accountkit.com/${this.language}/sdk.js`
      )
      tag.setAttribute('id', 'account-kit')
      tag.setAttribute('type', 'text/javascript')
      tag.onload = () => {
        /* eslint-disable camelcase */
        window.AccountKit_OnInteractive = this.onLoad.bind(this)
        /* eslint-enable camelcase */
      }
      document.head.appendChild(tag)
    },

    /**
     * Implementation of AccountKit_OnInteractive
     * Initializes the facebook authentication kit calling the init function.
     * @see https://developers.facebook.com/docs/accountkit/webjs/reference
     */
    onLoad () {
      const { appId, state, version, fbAppEventsEnabled, display } = this.$data
      window.AccountKit.init({
        appId,
        state,
        version,
        fbAppEventsEnabled,
        display
      })
    },
    /**
     * @param {*} loginParams @see https://developers.facebook.com/docs/accountkit/webjs/reference
     */
    login (loginParams, callback) {
      window.AccountKit.login(this.loginType, loginParams, callback)
    }
  }
}
</script>
