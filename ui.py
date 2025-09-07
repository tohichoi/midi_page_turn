from datetime import datetime
import os
import time
from time import sleep
from time import monotonic
from random import randint

# Suppress the pygame support prompt.
# This must be set before importing pygame.
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "1"

import pygame
import pygame.midi

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, DataTable, Sparkline, Digits, Label, Static
from textual import events, work
from textual.worker import get_current_worker
from textual.reactive import reactive
from textual.containers import Horizontal, Vertical

from rich.text import Text


from midi_page_turn2 import (
    sendkey, CCDATA, is_windows,
    VK_DOWN, VK_UP, VK_LEFT, VK_RIGHT,
    LEFT_PEDAL, MID_PEDAL
)


RECV_TIME_WINDOW = 30  # seconds


class ThreadQuit:
    pass


class TimeDisplay(Digits):
    """A widget to display elapsed time."""

    start_time = reactive(monotonic)
    time = reactive(0.0)
    total = reactive(0.0)

    def on_mount(self) -> None:
        """Event handler called when widget is added to the app."""
        self.update_timer = self.set_interval(1 / 60, self.update_time, pause=True)

    def update_time(self) -> None:
        """Method to update time to current."""
        self.time = self.total + (monotonic() - self.start_time)

    def watch_time(self, time: float) -> None:
        """Called when the time attribute changes."""
        minutes, seconds = divmod(time, 60)
        hours, minutes = divmod(minutes, 60)
        self.update(f"{hours:02,.0f}:{minutes:02.0f}:{seconds:05.2f}")

    def start(self) -> None:
        """Method to start (or resume) time updating."""
        self.start_time = monotonic()
        self.update_timer.resume()

    def stop(self):
        """Method to stop the time display updating."""
        self.update_timer.pause()
        self.total += monotonic() - self.start_time
        self.time = self.total

    def reset(self):
        """Method to reset the time display to zero."""
        self.total = 0
        self.time = 0
        
        
class MidiPageTurnApp(App):
    """A Textual app to configure MIDI page turner settings."""

    CSS_PATH = "ui.tcss"
    BINDINGS = [
        # ("d", "toggle_dark", "Toggle dark mode"),
        ("space", "start_receiving", "Select device and wait for messages"),
        ("f5", "refresh", "Refresh device list"),
        ("q", "quit", "Quit")
    ]

    # midi_data = reactive([randint(0, 256) for _ in range(RECV_TIME_WINDOW)])
    midi_data = reactive([0 for _ in range(RECV_TIME_WINDOW)])

    def __init__(self, driver_class = None, css_path = None, watch_css = False, ansi_color = False):
        pygame.init()
        pygame.midi.init()
        
        self.table = None
        super().__init__(driver_class, css_path, watch_css, ansi_color)

    def compose(self) -> ComposeResult:
        yield Header()

        self.table = DataTable()
        self.table.add_columns("ID", "TYPE", "NAME", "STATUS")
        self.table.cursor_type = "row"
        self.table.zebra_stripes = True
        self.table.focus()
        self.table.show_header = True

        yield Vertical(
            Vertical(
                Label("Select MIDI Input Device", id="title"),
                self.table,
                id="midi_devices_container"
            ),
            Vertical(
                Label("MIDI Input Events (number of events per second)", id="midi_label"),
                Sparkline(self.midi_data, summary_function=sum),
                Horizontal(
                    Static("0", id="midi_legend_min", classes="legend"),
                    Static(f"{RECV_TIME_WINDOW} seconds", id="midi_legend_max", classes="legend"),
                    id="midi_legend_container"
                ),
                id="midi_events_container"
            ),
            Horizontal(
                Static("PREV (CC 67)", id="turn_prev", classes="turn_style"),
                Static("NEXT (CC 66)", id="turn_next", classes="turn_style"),
                id="turn_event_container"
            ),
            TimeDisplay("00:00:00.00", id="midi_count"),
            id="main_container"
        )
        
        yield Footer()
        

    # def on_ready(self) -> None:
    #     self.update_clock()
    #     self.set_interval(1, self.update_clock)

    # def update_clock(self) -> None:
    #     clock = datetime.now().time()
    #     self.query_one(Digits).update(f"{clock:%T}")
    def init_midi(self):
        try:
            pygame.midi.init()
        except Exception as e:
            pass
        
    def update_midi_data(self, value):
        self.midi_data.append(value)
        if len(self.midi_data) > RECV_TIME_WINDOW:
            self.midi_data.pop(0)
        sparkline = self.query_one(Sparkline)
        sparkline.refresh()
        
    def update_turn_status(self, status):
        if status == LEFT_PEDAL:
            self.query_one("#turn_next", Static).styles.background = "green"
            self.query_one("#turn_prev", Static).styles.background = "black"
        elif status == MID_PEDAL:
            self.query_one("#turn_next", Static).styles.background = "black"
            self.query_one("#turn_prev", Static).styles.background = "green"
        else:
            self.query_one("#turn_next", Static).styles.background = "black"
            self.query_one("#turn_prev", Static).styles.background = "black"
            
        self.set_interval(1, lambda: self.update_turn_status(None), pause=True)
        
    async def on_key(self, event: events.Key) -> None:
        # Check if the table is focused and Space is pressed
        if self.table.has_focus and event.key == "space":
            self.midi_device = self.get_input_device()
            self.worker = self.action_start_receiving()

    def get_input_device(self) -> int | None:
        # Action when Space is pressed on the DataTable
        try:
            self.init_midi()

            inport = None
            
            row = self.table.cursor_row
            self.log(f"Enter pressed on row index: {row}")
            if row is None:
                raise Exception({"message": "No row selected", "servity": "error"})

            label = self.query_one("#midi_label")
            time_display = self.query_one(TimeDisplay)
            
            row_data = self.table.get_row_at(row)
            self.log(f"Enter pressed on row: {row_data}")
            inport = row_data[0]
            
            # check if the selected device is an input device
            if row_data[1] not in ("IN", "IN/OUT"):
                inport = None
                raise Exception({"message": f"Selected device is not an input device: {row_data[2]}", "servity": "error"})
            
            # check if the selected device is already opened
            if row_data[3] == "OPENED":
                inport = None
                time_display.stop()
                time_display.reset()
                self.worker.cancel()
                self.table.update_cell_at((row, 3), "CLOSED")
                raise Exception({"message": "Device closed", "servity": "information"})
            else:
                self.log(f"Selected MIDI input port: {inport}")
                label.update(f"🎹 Receiving MIDI Input Events {row_data[2]} (port {inport})")
                self.notify(f"Listening MIDI events ... ", severity="information")
                self.table.update_cell_at((row, 3), "OPENED")
                time_display.start()
        except Exception as e:
            self.log(e.args[0]['message'])
            self.notify(e.args[0]['message'], severity=e.args[0]['servity'])
        finally:
            return inport
        
    @work(exclusive=True, thread=True)
    def action_start_receiving(self) -> None:
        # Action when Space is pressed on the DataTable
        # inport = self.get_input_device()
        inport = self.midi_device
        if inport is None:
            return
        
        try:
            midi_in = None
            
            worker = get_current_worker()
            if worker.is_cancelled:
                # finally block will be executed
                return

            self.call_from_thread(self.log, "Listening MIDI events ... ")
            pygame.midi.init()
            midi_in = pygame.midi.Input(inport)
        
            start_time = time.time()
            delay_ms = 1000
            event_size = 0
            while True:
                worker = get_current_worker()
                if worker.is_cancelled:
                    break

                sleep(0)

                current_time = time.time()
                if (current_time - start_time) * 1000 >= delay_ms:
                    start_time = current_time
                    self.log(f"Need update MIDI data... {current_time}")
                    # self.call_from_thread(self.log, f"Need update MIDI data... {current_time}")
                    need_update = True
                    self.call_from_thread(self.log, f'event size: {event_size}')
                    
                else:
                    need_update = False
                    
                if not midi_in.poll():
                    #spinner.stop()
                    if need_update:
                        self.log(f"update MIDI data... {0}")
                        self.call_from_thread(self.update_midi_data, event_size)
                        event_size = 0
                    continue

                # spinner.start()

                # status, controller, value, ?, ?
                # [[176, 67, 127, 0], 41834]
                data = midi_in.read(256)

                for d in data:
                    st = d[0][0]
                    cc = d[0][1]
                    val = d[0][2]

                    # control message
                    # 0b1011CCCC : 1011 : control, CCCC: channel
                    # print('{:b}'.format(st & 0b10110000))
                    if st >> 4 != 0b1011:
                        continue

                    if cc not in CCDATA.keys():
                        break

                    # print(d)

                    # print(f'ControlCode : {cc}, Value: {val}')
                    if val > 0:
                        if CCDATA[cc][0]:
                            sendkey(CCDATA[cc][1])
                            self.call_from_thread(self.update_turn_status, cc)
                            CCDATA[cc][0] = False
                            # print('-'*20)
                            # print('')
                            # spinner.stop()
                            # pinner.write( '  🎼 {0} {1:d}'.format(('NEXT' if cc == LEFT_PEDAL else "PREV"), int(time.time())))
                        # spinner.start()
                        # spinner.ok('✔')
                        # print('-'*20)
                    else:  # val is zero (means end of control message)
                        CCDATA[cc][0] = True
                        
                event_size += len(data)
                    
        except Exception as e:
            self.log(f"Error in MIDI listening thread: {e}")
        finally:
            # self.call_from_thread(self.notify, "Exiting MIDI listening thread ... ")
            # label = self.call_from_thread(self.query_one, "#midi_label")
            if 'midi_in' in locals() and midi_in is not None and hasattr(midi_in, "get_open") and midi_in.get_open():
                midi_in.close()
            pygame.midi.quit()
            
            
    def read_available_devices(self):
        self.init_midi()
        
        # Populate the DataTable with MIDI device information
        for i in range(pygame.midi.get_count()):
            ret = pygame.midi.get_device_info(i)
            typestr = ''
            if ret[2] and ret[3]:
                typestr = "IN/OUT"
            elif ret[2]:
                typestr = "IN"
            elif ret[3]:
                typestr = "OUT"
            status = Text("OPENED", style="$text-success") if ret[4] else Text("CLOSED", style="$text-muted") 
            name = ret[1].decode("utf-8")
            self.table.add_row(i, typestr, name, status, key=str(i))
            
    async def on_mount(self) -> None:
        self.read_available_devices()
            
    async def action_quit(self):
        """Called when the 'q' key is pressed."""
        if hasattr(self, 'worker') and self.worker is not None:
            self.worker.cancel()
            try:
                while not self.worker.is_cancelled:
                    await self.worker.wait()
            except Exception as e:
                self.log(f"Error while waiting for worker to cancel: {e}")
        pygame.midi.quit()
        pygame.quit()
        
        self.exit()
        
    async def action_refresh(self) -> None:
        """Called when the 'f5' key is pressed."""
        try:
            if hasattr(self, 'worker') and self.worker is not None:
                self.worker.cancel()
                try:
                    while not self.worker.is_cancelled:
                        await self.worker.wait()
                except Exception as e:
                    self.log(f"Error while waiting for worker to cancel: {e}")
                    
            pygame.midi.quit()
            
            self.table.clear()
            self.read_available_devices()

            # label = self.query_one("#midi_label")
            # label.update("MIDI Input Events (number of events per second)")
            time_display = self.query_one(TimeDisplay)
            time_display.stop()
            time_display.reset()
            self.notify("MIDI device list refreshed", severity="information")
        except Exception as e:
            self.log(f"Error while refreshing MIDI devices: {e}")
            self.notify(f"Error while refreshing MIDI devices: {e}", severity="error")
        finally:
            return
        
        
if __name__ == "__main__":
    app = MidiPageTurnApp()
    app.run()
