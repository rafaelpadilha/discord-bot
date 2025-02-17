from src.player.youtube import download_song, get_song_url, get_youtube_playlist_songlist
from src.player.songcache import SongCache
from discord.ext.commands import Context
from discord import Embed, FFmpegPCMAudio
from queue import Queue
from datetime import timedelta
from asyncio import sleep
from re import match
from os import getenv

class Player():
    def __init__(self, bot) -> None:
        self.song_queue = {}
        self.bot = bot
        self.logger = bot.logger
        self.cache = SongCache(self.logger)
        self.IDLE_TIMEOUT = getenv("IDLE_TIMEOUT", 1)
        self.playing = False

    async def play(self, ctx: Context, play_text: str) -> None:
        if ctx.author.voice is None:
            await ctx.send("Você não está em um canal de voz")
            return

        user_voice_channel = ctx.author.voice.channel

        if ctx.voice_client is not None:
            if ctx.voice_client.channel != user_voice_channel:
                await ctx.send("O bot já está conectado em outro canal!")

        embed_msg = Embed(title=f":mag_right: **Procurando**: `{play_text}`",
                          color=0x550a8a)
        await ctx.send(embed=embed_msg)

        await self.handle_request(play_text, ctx)
        self.logger.info('Buscando a musica.')

    async def list(self, ctx: Context) -> None:
        queue = self.get_queue(ctx)
        if not queue.empty():
            list_buffer = ""
            queue_duration = 0
            for idx, song in enumerate(queue.queue, 1):
                requester = await self.bot.fetch_user(song.requester)
                list_buffer += f"**{idx}.** *" + song.title + "* " + \
                    f"`{timedelta(seconds=song.duration)}`" + f' {requester.mention}' +"\n"
                queue_duration += song.duration
            embed_msg = Embed(title=":play_pause: **Fila**",
                              description=list_buffer, color=0x550a8a)
            embed_msg.set_footer(
                text=f"Duração da fila: {str(timedelta(seconds=queue_duration))}")
            self.bot.loop.create_task(
                ctx.message.channel.send(embed=embed_msg))
            self.logger.info('O bot recuperou a fila de reprodução.')
        else:
            embed_msg = Embed(title="Fila vazia",
                              description="Adicione músicas :)", color=0xeb2828)
            self.bot.loop.create_task(
                ctx.message.channel.send(embed=embed_msg))
            self.logger.info(
                'O bot não recuperou a lista pois a fila está vazia.')

    async def leave(self, ctx: Context) -> None:
        user_voice_channel = ctx.author.voice.channel
        if ctx.voice_client.channel == user_voice_channel:
            queue = self.get_queue(ctx)
            await ctx.voice_client.disconnect()
            with queue.mutex:
                queue.queue.clear()
            self.playing = False
            self.logger.info(
                f'O bot desconectou do canal.')
        else:
            self.bot.loop.create_task(
                ctx.send("O usuário deve estar no mesmo canal do bot para desconectá-lo"))

    async def pause(self, ctx: Context) -> None:
        if ctx.author.voice is not None:
            if ctx.voice_client.channel == ctx.author.voice.channel:
                ctx.voice_client.pause()

    async def resume(self, ctx: Context) -> None:
        if ctx.author.voice is not None:
            if ctx.voice_client.channel == ctx.author.voice.channel:
                ctx.voice_client.resume()

    async def next(self, ctx: Context) -> None:
        if ctx.author.voice is not None:
            if ctx.voice_client.channel == ctx.author.voice.channel:
                ctx.voice_client.stop()

    def get_queue(self, ctx: Context) -> Queue:
        """
        Checks if queue exists
        Create one if it does not
        Return if exists
        """
        if not ctx.guild.id in self.song_queue:
            self.song_queue[ctx.guild.id] = Queue()
        return self.song_queue[ctx.guild.id]

    async def handle_request(self, play_text: str, ctx: Context,) -> None:
        is_youtube_playlist = match(
            "https://www.youtube.com/playlist*", play_text)
        is_youtube_link = match(
            "https://www.youtube.com/watch*|https://youtu.be/*", play_text)
        if is_youtube_playlist:
            self.add_playlist(play_text, ctx)
        elif is_youtube_link:
            self.add_song(play_text, ctx, link=True)
        else:
            self.add_song(play_text, ctx)

    def add_song(self, song_name: str, ctx: Context, link=False) -> None:
        """
        A parallel function to search, download the song and put on the queue
        Starts the player if it's not running
        """
        if not link:
            song_url = get_song_url(song_name)
        else:
            song_url = song_name

        id = str(match(r'.*watch\?v=(.*)', song_url).group(1))
        self.logger.info(f'ID:{id} \tURL:{song_url}')
        song = self.cache.get_song(id)
        if not song:
            self.logger.info('Musica nao encontrada em cache, baixando.')
            song = download_song('songs', song_url, requester=ctx.message.author)
            self.cache.add_song(song)

        if not song.requester:
            song.requester = str(ctx.message.author.id)

        self.cache.increment_plays(id)
        queue = self.get_queue(ctx)
        queue.put(song)
        self.logger.info('Musica adicionada na fila de reproducao.')

        if self.playing:
            embed_msg = Embed(title=f":thumbsup: **Adicionado a fila de reprodução**",
                                description=f"`{song.title}`", color=0x550a8a)
            embed_msg.set_footer(text=f"Posição: {len(queue.queue)}")
            self.bot.loop.create_task(
                ctx.message.channel.send(embed=embed_msg))
            self.logger.info(
                'O bot adicionou a música na fila de reprodução.')
        else:
            self.playing = True
            self.bot.loop.create_task(self.play_queue(ctx))

    def add_playlist(self, play_list_url: str, ctx: Context) -> None:
        """
        Downloads all songs from a playlist and put them on que queue
        """
        songs_url = get_youtube_playlist_songlist(play_list_url)
        embed_msg = Embed(title=f":notepad_spiral: **Playlist adicionada a fila** :thumbsup:",
                          description=f"`{play_list_url}`", color=0x550a8a)
        embed_msg.set_footer(text=f"Adicionado por {ctx.message.author}")
        self.bot.loop.create_task(ctx.message.channel.send(embed=embed_msg))
        for song_url in songs_url:
            self.add_song(song_url, ctx, link=True)
        self.logger.info('O bot adicionou as músicas da playlist.')

    async def play_queue(self, ctx: Context) -> None:
        self.playing = True
        if ctx.voice_client is None:
            await ctx.author.voice.channel.connect()

        queue = self.get_queue(ctx)
        voice_client = ctx.voice_client
        timer = 0
        self.logger.info('O bot está reproduzindo a fila.')
        while timer < self.IDLE_TIMEOUT:
            while not queue.empty():
                self.playing = True
                current_song = queue.get()
                embed_msg = Embed(title=f":arrow_forward: **Reproduzindo**",
                                  description=f"`{current_song.title}`", color=0x550a8a)
                embed_msg.set_thumbnail(url=current_song.thumb)
                requester = await self.bot.fetch_user(current_song.requester)
                if requester:
                    embed_msg.set_footer(
                        text=f"Adicionada por {requester.display_name}" , icon_url=requester.avatar_url)
                self.bot.loop.create_task(
                    ctx.message.channel.send(embed=embed_msg))
                voice_client.play(FFmpegPCMAudio(current_song.path))
                while voice_client.is_playing():
                    await sleep(1)
                self.playing = False
                timer = 0
            await sleep(1)
            timer += 1
        await voice_client.disconnect()
        self.logger.info('O bot desconectou do canal após reproduzir a fila.')
        return
    
    async def remove(self, ctx: Context, idx: str) -> None:
        """
        Remove song from the queue by index.
        """
        if ctx.author.voice is not None and ctx.voice_client is not None:
            if ctx.voice_client.channel == ctx.author.voice.channel:
                queue = self.get_queue(ctx)
                if queue.empty():
                    embed_msg = Embed(title="Fila vazia",
                              description="Adicione músicas :)", color=0xeb2828)
                    self.bot.loop.create_task(
                    ctx.message.channel.send(embed=embed_msg))
                    return
                if idx.isnumeric() and (abs(int(idx)) <= queue.qsize()):
                    del queue.queue[int(idx) - 1]
                    self.logger.info(f'O bot removeu a música de posição {int(idx)-1} da fila.')
                else:
                    embed_msg = Embed(title=f":x: **Posição inválida**", color=0xeb2828)
                    self.bot.loop.create_task(
                        ctx.message.channel.send(embed=embed_msg))
                    return
    
    async def clear(self, ctx: Context) -> None:
        """
        Clear queue.
        """
        if ctx.author.voice is not None and ctx.voice_client is not None:
            if ctx.voice_client.channel == ctx.author.voice.channel:
                queue = self.get_queue(ctx)

                if queue.empty():
                    embed_msg = Embed(title="Fila vazia",
                              description="Adicione músicas :)", color=0xeb2828)
                    self.bot.loop.create_task(
                    ctx.message.channel.send(embed=embed_msg))
                    return
                else:
                    with queue.mutex:
                        queue.queue.clear()
                    self.logger.info(f'O bot limpou a fila.')
                