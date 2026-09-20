# EfficientAI Enterprise License

Copyright (c) 2026 EfficientAI.tech

## Terms

The code and content within the `enterprise/` directory of this repository
is licensed under this Enterprise License Agreement. It is **not** covered
by the MIT License that applies to the rest of the repository.

Certain product capabilities in the main codebase are also gated behind a
valid EfficientAI Enterprise license key (`EFFICIENTAI_LICENSE`). Without a
valid key, those capabilities are unavailable or subject to open-source usage
limits as documented at https://efficientai.cloud.

### Permitted Use

You may use enterprise-licensed code and enterprise-gated product features
**only** if you hold a valid EfficientAI Enterprise license key issued by
EfficientAI.cloud.

A valid license grants you the right to:

- Deploy and run enterprise features in your own infrastructure
- Modify enterprise code for internal use within the scope of your license
- Unlock enterprise product capabilities according to the features encoded
  in your license JWT

### Restrictions

Without a valid enterprise license, you may **not**:

- Use, copy, modify, or distribute the enterprise-licensed code in
  production environments beyond the open-source limits
- Remove or circumvent the enterprise license validation mechanism
  (`EFFICIENTAI_LICENSE` / `license.key` in config)
- Sublicense, sell, or redistribute the enterprise-licensed code

### License Keys

Enterprise license keys are JWT tokens signed by EfficientAI. Set them via:

- Environment variable: `EFFICIENTAI_LICENSE`
- Config file: `license.key` in `config.yml`

Keys are available by contacting the EfficientAI team:

- **Email:** sales@efficientai.com / aadhar@efficientai.cloud
- **Website:** https://efficientai.cloud

### Disclaimer

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
