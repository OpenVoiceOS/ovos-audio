# Changelog

## [2.2.1a1](https://github.com/OpenVoiceOS/ovos-audio/tree/2.2.1a1) (2026-08-26)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/2.2.0a2...2.2.1a1)

**Closed issues:**

- Changing tts.module does not reload the engine unless the new plugin has a config block [\#186](https://github.com/OpenVoiceOS/ovos-audio/issues/186)

**Merged pull requests:**

- fix: reload the TTS engine when the plugin changes [\#187](https://github.com/OpenVoiceOS/ovos-audio/pull/187) ([JarbasAl](https://github.com/JarbasAl))
- docs: rewrite README in Simplified Technical English [\#178](https://github.com/OpenVoiceOS/ovos-audio/pull/178) ([JarbasAl](https://github.com/JarbasAl))

## [2.2.0a2](https://github.com/OpenVoiceOS/ovos-audio/tree/2.2.0a2) (2026-08-15)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/2.2.0a1...2.2.0a2)

**Merged pull requests:**

- refactor: drop redundant legacy dual bus subscriptions [\#179](https://github.com/OpenVoiceOS/ovos-audio/pull/179) ([JarbasAl](https://github.com/JarbasAl))

## [2.2.0a1](https://github.com/OpenVoiceOS/ovos-audio/tree/2.2.0a1) (2026-08-11)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/2.1.1a2...2.2.0a1)

**Merged pull requests:**

- feat: run ServiceInstaller \(install plugins into the audio env over the bus\) [\#181](https://github.com/OpenVoiceOS/ovos-audio/pull/181) ([JarbasAl](https://github.com/JarbasAl))

## [2.1.1a2](https://github.com/OpenVoiceOS/ovos-audio/tree/2.1.1a2) (2026-07-17)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/2.1.1a1...2.1.1a2)

**Merged pull requests:**

- refactor: consume transformer runner services from ovos-plugin-manager [\#175](https://github.com/OpenVoiceOS/ovos-audio/pull/175) ([JarbasAl](https://github.com/JarbasAl))

## [2.1.1a1](https://github.com/OpenVoiceOS/ovos-audio/tree/2.1.1a1) (2026-06-28)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/2.1.0a1...2.1.1a1)

**Merged pull requests:**

- fix: lift ovos-spec-tools upper bound \(spec-tools 1.x\) [\#173](https://github.com/OpenVoiceOS/ovos-audio/pull/173) ([JarbasAl](https://github.com/JarbasAl))

## [2.1.0a1](https://github.com/OpenVoiceOS/ovos-audio/tree/2.1.0a1) (2026-06-27)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/2.0.2a1...2.1.0a1)

**Merged pull requests:**

- feat: adopt AUDIO-1 spec output topics \(dual-namespace\) [\#171](https://github.com/OpenVoiceOS/ovos-audio/pull/171) ([JarbasAl](https://github.com/JarbasAl))

## [2.0.2a1](https://github.com/OpenVoiceOS/ovos-audio/tree/2.0.2a1) (2026-06-25)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/2.0.1a1...2.0.2a1)

**Merged pull requests:**

- fix: floor media-plugin chromecast/spotify to bus-client-2.x prereleases [\#169](https://github.com/OpenVoiceOS/ovos-audio/pull/169) ([JarbasAl](https://github.com/JarbasAl))

## [2.0.1a1](https://github.com/OpenVoiceOS/ovos-audio/tree/2.0.1a1) (2026-06-25)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/2.0.0a1...2.0.1a1)

**Merged pull requests:**

- fix: media-plugin backends replace deprecated audio-plugin-\*; single-source pyproject [\#167](https://github.com/OpenVoiceOS/ovos-audio/pull/167) ([JarbasAl](https://github.com/JarbasAl))

## [2.0.0a1](https://github.com/OpenVoiceOS/ovos-audio/tree/2.0.0a1) (2026-06-25)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/1.3.0a1...2.0.0a1)

**Breaking changes:**

- feat!: migrate audio output to OVOS spec bus namespace [\#165](https://github.com/OpenVoiceOS/ovos-audio/pull/165) ([JarbasAl](https://github.com/JarbasAl))

## [1.3.0a1](https://github.com/OpenVoiceOS/ovos-audio/tree/1.3.0a1) (2026-06-24)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/1.2.3a1...1.3.0a1)

**Merged pull requests:**

- feat: consume both bus namespaces for speak and stop \(PIPELINE-1 §9.6, STOP-1 §5.3\) [\#158](https://github.com/OpenVoiceOS/ovos-audio/pull/158) ([JarbasAl](https://github.com/JarbasAl))

## [1.2.3a1](https://github.com/OpenVoiceOS/ovos-audio/tree/1.2.3a1) (2026-06-20)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/1.2.2a1...1.2.3a1)

**Merged pull requests:**

- fix: allow ovos-bus-client 2.x [\#161](https://github.com/OpenVoiceOS/ovos-audio/pull/161) ([JarbasAl](https://github.com/JarbasAl))

## [1.2.2a1](https://github.com/OpenVoiceOS/ovos-audio/tree/1.2.2a1) (2026-06-06)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/1.2.1a1...1.2.2a1)

**Merged pull requests:**

- fix\(deps\): allow ovos-bus-client 2.x \(widen cap to \<3.0.0\) [\#159](https://github.com/OpenVoiceOS/ovos-audio/pull/159) ([JarbasAl](https://github.com/JarbasAl))

## [1.2.1a1](https://github.com/OpenVoiceOS/ovos-audio/tree/1.2.1a1) (2026-03-16)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-audio/compare/1.2.0...1.2.1a1)

**Merged pull requests:**

- Update phoonnx requirement from \<1.0.0,\>=0.5.4 to \>=0.5.4,\<2.0.0 in /requirements [\#151](https://github.com/OpenVoiceOS/ovos-audio/pull/151) ([dependabot[bot]](https://github.com/apps/dependabot))



\* *This Changelog was automatically generated by [github_changelog_generator](https://github.com/github-changelog-generator/github-changelog-generator)*
