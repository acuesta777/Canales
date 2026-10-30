(*
TTS SINGLE — Un solo personaje con fallback automático
-------------------------------------------------------
Uso desde terminal / Claude:
  osascript tts_single.applescript /ruta/carpeta/personaje/

Flujo:
  1) Toma el .txt de la carpeta del personaje
  2) Intenta con AI33 (provider primario)
  3) Si falla o timeout → cambia a AI84 automáticamente
  4) Guarda el MP3 en la misma carpeta como [personaje].mp3

Sin diálogos. Sin intervención manual.
*)

-- ================== CONFIG (editable) ==================
property PRIMARY_PROVIDER : "AI33"
property FALLBACK_PROVIDER : "AI84"
property WAIT_MINUTES_MAX : 15
property POLL_SECONDS : 45

-- ================== HELPERS ==================
on readFile(p)
	try
		return do shell script "cat " & quoted form of p & " | tr -d '\n\r\t '"
	on error
		return ""
	end try
end readFile

on ensureDir(p)
	do shell script "mkdir -p " & quoted form of p
end ensureDir

on fileNonEmpty(p)
	try
		do shell script "test -s " & quoted form of p
		return true
	on error
		return false
	end try
end fileNonEmpty

on writeTextFileUTF8(posixPath, contentText)
	set py to "import sys; open(sys.argv[1],'w',encoding='utf-8').write(sys.argv[2])"
	do shell script "/usr/bin/python3 -c " & quoted form of py & " " & quoted form of posixPath & " " & quoted form of contentText
end writeTextFileUTF8

on nowStamp()
	return do shell script "date +%Y%m%d-%H%M%S"
end nowStamp

-- ================== FUNCIÓN TTS POR PROVIDER ==================
on runTTS(providerName, charFolder, txtFile, charName)
	set homeDir to POSIX path of (path to home folder)

	-- Rutas de credenciales
	if providerName is "AI33" then
		set keyFile to homeDir & ".ai33_key"
		set voiceFile to homeDir & ".ai33_voice_id"
		set scriptFile to homeDir & ".ai33_batch_script_path"
	else
		set keyFile to homeDir & ".ai84_key"
		set voiceFile to homeDir & ".ai84_voice_id"
		set scriptFile to homeDir & ".ai84_batch_script_path"
	end if

	-- Leer credenciales
	set voiceId to my readFile(voiceFile)
	set batchScript to my readFile(scriptFile)

	if voiceId is "" then
		log "[" & providerName & "] Sin voice ID."
		return false
	end if
	if batchScript is "" then
		log "[" & providerName & "] Sin ruta de script batch."
		return false
	end if
	try
		do shell script "test -f " & quoted form of batchScript
	on error
		log "[" & providerName & "] Script batch no existe: " & batchScript
		return false
	end try

	-- Directorio temporal
	set ts to my nowStamp()
	set workDir to "/tmp/tts_single_" & ts & "_" & (do shell script "uuidgen") & "/"
	set parte01Dir to workDir & "tts_in/01/"
	my ensureDir(parte01Dir)

	-- Copiar TXT como parte_01.txt
	set dstTxt to parte01Dir & "parte_01.txt"
	do shell script "cp " & quoted form of txtFile & " " & quoted form of dstTxt

	-- Manifest
	set manifestPath to workDir & "manifest_" & ts & ".txt"
	my writeTextFileUTF8(manifestPath, dstTxt & linefeed)

	-- Marker de tiempo
	set audiosRoot to homeDir & "Downloads/audios/"
	my ensureDir(audiosRoot)
	set markerPath to audiosRoot & "_MARK_SINGLE_" & ts & ".txt"
	do shell script "touch " & quoted form of markerPath

	-- Limpiar parte_01/ vieja para evitar SKIP
	try
		do shell script "rm -rf " & quoted form of (audiosRoot & "parte_01/")
	end try

	-- Invocar TTS
	try
		do shell script "/usr/bin/osascript " & quoted form of batchScript & " " & quoted form of manifestPath & " " & quoted form of voiceId
	on error e
		log "[" & providerName & "] Error al invocar: " & e
		try
			do shell script "rm -f " & quoted form of markerPath
			do shell script "rm -rf " & quoted form of workDir
		end try
		return false
	end try

	-- Esperar MP3
	set startEpoch to (do shell script "date +%s") as integer
	set waitSecondsMax to (WAIT_MINUTES_MAX * 60)
	set foundMp3 to ""

	repeat
		set findCmd to "find " & quoted form of (audiosRoot & "parte_01/") & " -maxdepth 1 -type f -name '*.mp3' -newer " & quoted form of markerPath & " 2>/dev/null | head -n 1"
		try
			set foundMp3 to do shell script findCmd
		on error
			set foundMp3 to ""
		end try

		if foundMp3 is not "" then exit repeat

		set nowEpoch to (do shell script "date +%s") as integer
		if (nowEpoch - startEpoch) > waitSecondsMax then
			log "[" & providerName & "] Timeout después de " & WAIT_MINUTES_MAX & " minutos."
			exit repeat
		end if

		delay POLL_SECONDS
	end repeat

	-- Limpiar marker
	try
		do shell script "rm -f " & quoted form of markerPath
	end try

	if foundMp3 is "" then
		try
			do shell script "rm -rf " & quoted form of workDir
		end try
		return false
	end if

	-- Copiar MP3 a carpeta del personaje
	set finalMp3 to charFolder & charName & ".mp3"
	do shell script "cp " & quoted form of foundMp3 & " " & quoted form of finalMp3

	-- Limpiar temporales
	try
		do shell script "rm -rf " & quoted form of (audiosRoot & "parte_01/")
		do shell script "rm -rf " & quoted form of workDir
	end try

	return true
end runTTS

-- ================== MAIN ==================
on run argv
	if (count of argv) is 0 then
		error "Uso: osascript tts_single.applescript /ruta/carpeta/personaje/"
	end if

	set charFolder to item 1 of argv
	if charFolder does not end with "/" then set charFolder to charFolder & "/"

	-- Encontrar TXT en la carpeta
	set txtFile to ""
	try
		set txtFile to do shell script "find " & quoted form of charFolder & " -maxdepth 1 -type f -name '*.txt' | head -n 1"
	end try
	if txtFile is "" then error "No encontré ningún .txt en: " & charFolder

	-- Nombre del personaje
	set charName to do shell script "/usr/bin/python3 -c \"import os,sys; print(os.path.splitext(os.path.basename(sys.argv[1]))[0])\" " & quoted form of txtFile

	log "Procesando: " & charName & " con " & PRIMARY_PROVIDER

	-- Intentar con provider primario
	set success to my runTTS(PRIMARY_PROVIDER, charFolder, txtFile, charName)

	-- Fallback si falla
	if success is false then
		log "[FALLBACK] " & PRIMARY_PROVIDER & " falló. Cambiando a " & FALLBACK_PROVIDER
		display notification "Cambiando de " & PRIMARY_PROVIDER & " a " & FALLBACK_PROVIDER & "..." with title "TTS Single — Fallback"
		set success to my runTTS(FALLBACK_PROVIDER, charFolder, txtFile, charName)
	end if

	-- Resultado final
	if success then
		display notification charName & ".mp3 listo en la carpeta del personaje." with title "TTS Single ✓"
	else
		display notification "Fallaron " & PRIMARY_PROVIDER & " y " & FALLBACK_PROVIDER & ". Sin audio." with title "TTS Single ✗"
		error "No se pudo generar audio para: " & charName
	end if
end run
