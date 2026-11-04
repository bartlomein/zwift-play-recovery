# Firmware and public distribution

Checked November 3, 2026. This is a project distribution decision, not a legal opinion about enforceability or repair/interoperability exceptions in any jurisdiction.

## Do not bundle the captured firmware yet

The captured `.bin` images, signed `.dat` headers and reconstructed ZIP have no identified redistribution license. Capturing bytes from an update is not evidence of permission to publish them. A signature authenticates content under a key; it does not grant a copyright license.

Zwift's [Terms of Service](https://us.zwift.com/policies/terms-of-service), updated June 2, 2026, restrict distribution of Platform material in section 5(a)(v), contain connected-device firmware and reverse-engineering restrictions in 5(a)(viii–ix), and address unofficial interacting applications in 5(a)(xiii). The [EULA](https://support.zwift.com/en_us/end-user-license-agreement-rymuiTZr) is another relevant document. Whether every clause applies to this recovery tool requires a proper review; a code-only repo does not automatically settle that question.

Until written permission or an applicable redistribution license is established, keep firmware out of Git, releases, package registries, issue attachments and demo assets. The repository ignores firmware extensions and publishes only verification metadata and original tool source. Publication permission is not claimed for the tool itself.

## How users supply firmware

Ask Zwift for an authorized Play recovery package. There is no confirmed public download URL bundled here, and no promise that support will provide a file. This is the largest remaining obstacle to a completely self-contained beginner experience.

When the file is available, run:

```sh
zwift-play firmware /path/to/update.zip
```

The wizard accepts the same path. A locally reconstructed folder containing `application.bin` and `application.dat` also works. The loader never extracts archive paths to disk. It bounds file sizes and rejects duplicate members, invalid manifests, unsupported images and bad signatures.

## Supported application fingerprint

| Item | Value |
| --- | --- |
| Version | 2.0.1 |
| Hardware ID | RC1 (`0x524331`) |
| Application size | 180488 bytes |
| Application SHA-256 | `73f09fd1c5721b2ed7498d486387f23711af9abfdd7f3762ef29ae1f112c0333` |
| Init SHA-256 | `b3f39184069c2c8c30edbc9f6822880d000c9501b0429e2e6962cf757d7f8cdb` |

The same application was observed in separate Companion transfers for left and right identities. This is evidence for that specific package, not permission to use arbitrary firmware across models. Only the signed application is sent; a SoftDevice mismatch stops recovery.

## Permission request draft — not sent

> We built an independent diagnostic/recovery utility for owners of Zwift Play controllers left in Secure DFU after failed Companion updates. It sends an unmodified signed application without bypassing device validation. Would Zwift authorize public distribution of this recovery tool and the matching firmware package, or provide an official user-downloadable recovery package? We would like clear written terms for hosting, versions, attribution and permitted use. Until then, our local prototype keeps the firmware separate.
