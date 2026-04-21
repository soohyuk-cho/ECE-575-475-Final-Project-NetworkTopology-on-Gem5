"""Hub-and-spoke (star) topology for Ruby simple or Garnet networks.

Router 0 is the hub; routers 1 .. num_cpus-1 are spokes, each connected
only to the hub.

Use ``--topology Star --network garnet`` with default table routing
(``--routing-algorithm 0``) and ``--mesh-rows 0``. Do not use XY or custom
mesh routing on this topology.
"""

from common import FileSystemConfig
from topologies.BaseTopology import SimpleTopology

from m5.objects import *
from m5.params import *


class Star(SimpleTopology):
    description = "Star"

    def makeTopology(self, options, network, IntLink, ExtLink, Router):
        nodes = self.nodes

        num_routers = options.num_cpus
        assert num_routers >= 2, (
            "Star topology needs at least 2 routers (num_cpus): "
            "one hub and one spoke."
        )

        link_latency = options.link_latency
        router_latency = options.router_latency

        cntrls_per_router, remainder = divmod(len(nodes), num_routers)

        routers = [
            Router(router_id=i, latency=router_latency)
            for i in range(num_routers)
        ]
        network.routers = routers

        link_count = 0

        network_nodes = []
        remainder_nodes = []
        for node_index in range(len(nodes)):
            if node_index < (len(nodes) - remainder):
                network_nodes.append(nodes[node_index])
            else:
                remainder_nodes.append(nodes[node_index])

        ext_links = []
        for i, n in enumerate(network_nodes):
            cntrl_level, router_id = divmod(i, num_routers)
            assert cntrl_level < cntrls_per_router
            ext_links.append(
                ExtLink(
                    link_id=link_count,
                    ext_node=n,
                    int_node=routers[router_id],
                    latency=link_latency,
                )
            )
            link_count += 1

        for i, node in enumerate(remainder_nodes):
            assert node.type == "DMA_Controller"
            assert i < remainder
            ext_links.append(
                ExtLink(
                    link_id=link_count,
                    ext_node=node,
                    int_node=routers[0],
                    latency=link_latency,
                )
            )
            link_count += 1

        network.ext_links = ext_links

        int_links = []
        hub = routers[0]
        # connect all spoke routers to the hub router
        for i in range(1, num_routers):
            spoke = routers[i]
            int_links.append(
                IntLink(
                    link_id=link_count,
                    src_node=hub,
                    dst_node=spoke,
                    latency=link_latency,
                )
            )
            link_count += 1
            int_links.append(
                IntLink(
                    link_id=link_count,
                    src_node=spoke,
                    dst_node=hub,
                    latency=link_latency,
                )
            )
            link_count += 1

        network.int_links = int_links

    def registerTopology(self, options):
        for i in range(options.num_cpus):
            FileSystemConfig.register_node(
                [i], MemorySize(options.mem_size) // options.num_cpus, i
            )
